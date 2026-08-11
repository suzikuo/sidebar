from __future__ import annotations

import base64
import json
import os
import stat
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtWebView import QWebView, QWebViewSettings
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core.api_gateway import ApiRegistry

from .api_bridge import WebApiBridge
from .runtime import detect_webview2_runtime, missing_runtime_message


_BRIDGE_TITLE_PREFIX = "__AGILE_TILES_BRIDGE__:"
_BRIDGE_FRAGMENT_PREFIX = "agile-tiles-bridge:"
_MAX_ENTRY_BYTES = 4 * 1024 * 1024
_SCRIPT_CHUNK_CHARS = 8 * 1024


def resolve_web_entry(content_root, entry="index.html"):
    root = Path(content_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Web content root must be a directory.")

    entry_path = root.joinpath(*_safe_relative_parts(entry))
    if not entry_path.is_file() or _contains_link_or_reparse(root, entry_path):
        raise ValueError("Web entry must be a file inside the content root.")
    return root, entry_path


def is_web_url_allowed(url: QUrl, content_root: Path):
    scheme = url.scheme().lower()
    if scheme == "about":
        return url.toString() == "about:blank"
    if scheme != "file" or not url.isLocalFile():
        return False

    try:
        root = Path(os.path.abspath(content_root))
        requested_path = Path(os.path.abspath(url.toLocalFile()))
        requested_path.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return False
    return not _contains_link_or_reparse(root, requested_path)


class _SingleFileEntryParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.document_parts: list[str] = []
        self.script_parts: list[str] = []
        self._inside_script = False

    def handle_starttag(self, tag, attrs):
        normalized_tag = tag.casefold()
        normalized_attrs = {
            str(name).casefold(): value
            for name, value in attrs
            if name is not None
        }
        if normalized_tag == "script":
            if self._inside_script or any(name.casefold() == "src" for name, _ in attrs):
                raise ValueError("Web entry scripts must be inline and non-nested.")
            self._inside_script = True
            return
        if (
            normalized_tag == "link"
            and str(normalized_attrs.get("rel") or "").casefold() == "stylesheet"
            and "href" in normalized_attrs
        ):
            raise ValueError("Web entry stylesheets must be inline.")
        self._append_document(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if tag.casefold() == "script":
            raise ValueError("Web entry scripts must contain application code.")
        self._append_document(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag.casefold() == "script":
            if not self._inside_script:
                raise ValueError("Web entry contains an unmatched script tag.")
            self._inside_script = False
            return
        self._append_document(f"</{tag}>")

    def handle_data(self, data):
        if self._inside_script:
            self.script_parts.append(data)
        else:
            self.document_parts.append(data)

    def handle_entityref(self, name):
        self._append_document(f"&{name};")

    def handle_charref(self, name):
        self._append_document(f"&#{name};")

    def handle_comment(self, data):
        self._append_document(f"<!--{data}-->")

    def handle_decl(self, decl):
        self._append_document(f"<!{decl}>")

    def handle_pi(self, data):
        self._append_document(f"<?{data}>")

    def _append_document(self, value: str):
        if self._inside_script:
            raise ValueError("Web entry script markup is invalid.")
        self.document_parts.append(value)


def prepare_web_entry(entry_path: Path, *, max_bytes: int = _MAX_ENTRY_BYTES):
    content = Path(entry_path).read_bytes()
    if not content or len(content) > max_bytes:
        raise ValueError("Web entry must be a non-empty single HTML file up to 4 MiB.")
    try:
        document = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Web entry must be UTF-8 HTML.") from exc

    parser = _SingleFileEntryParser()
    parser.feed(document)
    parser.close()
    if parser._inside_script or not parser.script_parts:
        raise ValueError("Web entry must contain an inline application script.")

    document_without_scripts = "".join(parser.document_parts).encode("utf-8")
    encoded = base64.b64encode(document_without_scripts)
    url = QUrl.fromEncoded(b"data:text/html;charset=utf-8;base64," + encoded)
    return url, "\n".join(parser.script_parts)


def build_web_entry_url(entry_path: Path, *, max_bytes: int = _MAX_ENTRY_BYTES) -> QUrl:
    return prepare_web_entry(entry_path, max_bytes=max_bytes)[0]


def _safe_relative_parts(value) -> tuple[str, ...]:
    normalized = str(value or "").strip().replace("\\", "/")
    windows_path = PureWindowsPath(normalized)
    posix_path = PurePosixPath(normalized)
    if (
        not normalized
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise ValueError("Web entry must be a safe relative path.")
    return tuple(posix_path.parts)


def _contains_link_or_reparse(root: Path, target: Path) -> bool:
    try:
        relative = target.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        try:
            path_stat = current.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            return True
        attributes = getattr(path_stat, "st_file_attributes", 0)
        if stat.S_ISLNK(path_stat.st_mode) or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            return True
    return False


class WebPluginHost(QWidget):
    """Embeddable local WebView2 host with a lazy native QWindow container."""

    load_succeeded = Signal()
    load_failed = Signal(str)

    def __init__(
        self,
        registry: ApiRegistry,
        owner_id: str,
        content_root,
        *,
        entry: str = "index.html",
        capabilities: Iterable[str] = (),
        autoload: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.content_root, self.entry_path = resolve_web_entry(content_root, entry)
        self._disposed = False
        self._loaded = False
        self._page_script_started = False
        self._page_script = ""
        self._page_script_chunks: list[str] = []
        self._ready_probe_attempts = 0
        self._last_request_notification = ""

        self.bridge = WebApiBridge(
            registry,
            owner_id,
            capabilities,
            parent=self,
        )
        self.bridge.event_ready.connect(self._publish_event)

        self.view = QWidget(self)
        self._web_view = None
        self._view_container = None
        self._bridge_poll_timer = QTimer(self)
        self._bridge_poll_timer.setInterval(50)
        self._bridge_poll_timer.timeout.connect(self._poll_bridge_title)

        container_layout = QVBoxLayout(self.view)
        container_layout.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        if autoload:
            QTimer.singleShot(0, self.load)

    def _ensure_web_view(self) -> bool:
        if self._web_view is not None:
            return True

        if not detect_webview2_runtime()["available"]:
            self._fail(missing_runtime_message())
            return False

        web_view = QWebView()
        settings = web_view.settings()
        settings.setAttribute(
            QWebViewSettings.WebAttribute.JavaScriptEnabled,
            True,
        )

        web_view.loadingChanged.connect(self._on_loading_changed)
        web_view.urlChanged.connect(self._on_url_changed)
        web_view.titleChanged.connect(self._on_title_changed)
        view_container = QWidget.createWindowContainer(web_view, self.view)
        view_container.setObjectName("webview2_container")
        self.view.layout().addWidget(view_container)
        self._web_view = web_view
        self._view_container = view_container
        return True

    def load(self):
        if self._disposed:
            raise RuntimeError("Web plugin host has been disposed.")
        if not self._ensure_web_view():
            return
        entry_url, self._page_script = prepare_web_entry(self.entry_path)
        self._entry_url = entry_url
        self._web_view.setUrl(entry_url)
        for delay_ms in (250, 500, 1000, 2000, 4000):
            QTimer.singleShot(delay_ms, self._probe_document_ready)

    def _on_title_changed(self, title: str):
        if self._disposed or not str(title).startswith(_BRIDGE_TITLE_PREFIX):
            return
        request_id = str(title)[len(_BRIDGE_TITLE_PREFIX):]
        self._queue_native_request(request_id)

    def _queue_native_request(self, request_id: str):
        if (
            not request_id
            or request_id == self._last_request_notification
            or self._web_view is None
        ):
            return
        self._last_request_notification = request_id
        QTimer.singleShot(
            0,
            self._take_native_requests,
        )

    def _take_native_requests(self):
        if self._disposed or self._web_view is None:
            return
        self._web_view.runJavaScript(
            "window.__agileTilesBridgeTakeRequests?.() ?? '[]'",
            self._handle_native_requests,
        )

    def _handle_native_requests(self, requests_json):
        if self._disposed or not isinstance(requests_json, str):
            return
        try:
            request_items = json.loads(requests_json)
        except json.JSONDecodeError:
            return
        if not isinstance(request_items, list):
            return
        for request in request_items:
            self._handle_native_request(None, request)

    def _poll_bridge_title(self):
        if self._disposed or self._web_view is None:
            return
        self._on_title_changed(self._web_view.title())

    def _handle_native_request(self, expected_id: str, request_json):
        if self._disposed:
            return
        if isinstance(request_json, dict):
            request = request_json
        elif isinstance(request_json, str):
            try:
                request = json.loads(request_json)
            except (TypeError, json.JSONDecodeError):
                self._deliver_error(
                    expected_id,
                    "INVALID_REQUEST",
                    "Bridge request is not valid JSON.",
                )
                return
        else:
            return

        request_id = request.get("id") if isinstance(request, dict) else None
        route = request.get("route") if isinstance(request, dict) else None
        payload = request.get("payload", {}) if isinstance(request, dict) else None
        if (
            request.get("type") != "invoke"
            or not isinstance(request_id, str)
            or not request_id
            or (expected_id is not None and request_id != expected_id)
            or not isinstance(route, str)
            or not isinstance(payload, dict)
        ):
            self._deliver_error(
                expected_id or (request_id if isinstance(request_id, str) else ""),
                "INVALID_REQUEST",
                "Bridge request fields are invalid.",
            )
            return

        result = self.bridge.process_request(
            route,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            request_id,
        )
        encoded_result = self.bridge.encode_result(result)
        self.bridge.response_ready.emit(request_id, encoded_result)
        self._deliver_to_page({"type": "response", "id": request_id, "result": result})

    def _deliver_error(self, request_id: str, code: str, message: str):
        result = {"ok": False, "code": code, "message": message}
        self.bridge.response_ready.emit(request_id, self.bridge.encode_result(result))
        self._deliver_to_page({"type": "response", "id": request_id, "result": result})

    def _publish_event(self, event_name: str, payload_json: str):
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            return
        self._deliver_to_page({"type": "event", "event": event_name, "payload": payload})

    def _deliver_to_page(self, message):
        if self._disposed or self._web_view is None:
            return
        encoded = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        self._web_view.runJavaScript(
            "window.__agileTilesBridgeDeliver?.(" + encoded + ")",
            lambda _result: None,
        )

    def _on_loading_changed(self, info):
        if self._disposed:
            return
        try:
            status = info.status()
            status_name = getattr(status, "name", str(status))
            if "Succeeded" in status_name or status == 2:
                QTimer.singleShot(100, self._probe_document_ready)
            elif "Failed" in status_name or status == 3:
                message = info.errorString() or "The local web interface could not be loaded."
                if "COREWEBVIEW2_WEB_ERROR_STATUS_UNKNOWN" in message:
                    QTimer.singleShot(0, lambda reason=message: self._verify_unknown_failure(reason))
                else:
                    self._fail(message)
        except Exception as error:
            self._fail(str(error))

    def _verify_unknown_failure(self, message: str):
        if self._disposed or self._web_view is None:
            return
        self._web_view.runJavaScript(
            "document.readyState",
            lambda state, reason=message: self._on_ready_state_after_unknown_failure(
                state, reason
            ),
        )

    def _probe_document_ready(self):
        if self._disposed or self._web_view is None or self._page_script_started:
            return
        self._ready_probe_attempts += 1
        self._web_view.runJavaScript(
            "document.readyState",
            self._on_ready_probe_result,
        )

    def _on_ready_probe_result(self, state):
        if self._disposed or self._page_script_started:
            return
        if state in {"interactive", "complete"}:
            self._run_page_script()
        elif self._ready_probe_attempts < 80:
            QTimer.singleShot(50, self._probe_document_ready)
        else:
            self._fail("The local web interface did not become ready.")

    def _on_ready_state_after_unknown_failure(self, state, message: str):
        if self._disposed:
            return
        if state in {"interactive", "complete"}:
            self._run_page_script()
        else:
            self._fail(message)

    def _run_page_script(self):
        if self._disposed or self._web_view is None or self._page_script_started:
            return
        if not self._page_script:
            self._fail("Web entry application script is unavailable.")
            return
        self._page_script_started = True
        self._page_script_chunks = [
            self._page_script[index:index + _SCRIPT_CHUNK_CHARS]
            for index in range(0, len(self._page_script), _SCRIPT_CHUNK_CHARS)
        ]
        self._inject_page_script_chunk(0)

    def _inject_page_script_chunk(self, index: int):
        if self._disposed or self._web_view is None:
            return
        if index >= len(self._page_script_chunks):
            self._web_view.runJavaScript(
                "(() => {"
                "const source = window.__agileTilesBundleSource || '';"
                "delete window.__agileTilesBundleSource;"
                "try { (0, eval)(source); return true; }"
                "catch (error) { window.__agileTilesBundleError = String(error?.stack || error); return false; }"
                "})()",
                self._on_page_script_evaluated,
            )
            return

        chunk_json = json.dumps(self._page_script_chunks[index], ensure_ascii=True)
        assignment = "=" if index == 0 else "+="
        self._web_view.runJavaScript(
            f"window.__agileTilesBundleSource {assignment} {chunk_json}; true",
            lambda _result, next_index=index + 1: self._inject_page_script_chunk(
                next_index
            ),
        )

    def _on_page_script_evaluated(self, succeeded):
        if self._disposed:
            return
        if succeeded is True:
            self._mark_loaded()
            self._bridge_poll_timer.start()
        else:
            self._fail("Web entry application script could not be evaluated.")

    def _mark_loaded(self):
        if self._loaded or self._disposed:
            return
        self._loaded = True
        self.load_succeeded.emit()

    def _on_url_changed(self, url):
        if self._disposed or self._web_view is None or not hasattr(self, "_entry_url"):
            return
        document_url = QUrl(url)
        fragment = url.fragment()
        document_url.setFragment(None)
        if document_url == self._entry_url:
            if fragment.startswith(_BRIDGE_FRAGMENT_PREFIX):
                request_id = fragment[len(_BRIDGE_FRAGMENT_PREFIX):]
                self._queue_native_request(request_id)
            return
        if url != self._entry_url:
            self._web_view.setUrl(self._entry_url)

    def _fail(self, message: str):
        if not self._disposed:
            self.load_failed.emit(str(message))

    def publish_event(self, event_name: str, payload=None):
        if self._disposed:
            return
        self.bridge.publish_event(event_name, payload or {})

    def dispose(self):
        """Release the WebView2 page and native bridge exactly once."""
        if self._disposed:
            return
        self._disposed = True
        self._bridge_poll_timer.stop()
        if self._web_view is not None:
            web_view = self._web_view
            self._web_view = None
            try:
                web_view.stop()
            except RuntimeError:
                pass
            try:
                web_view.close()
            except RuntimeError:
                pass
        if self._view_container is not None:
            view_container = self._view_container
            self._view_container = None
            self.view.layout().removeWidget(view_container)
            view_container.deleteLater()
        self.view.deleteLater()
        self.bridge.deleteLater()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
