from pathlib import Path
from typing import Iterable

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from core.api_gateway import ApiRegistry

from .api_bridge import WebApiBridge


def resolve_web_entry(content_root, entry="index.html"):
    root = Path(content_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Web content root must be a directory.")

    entry_path = (root / str(entry or "")).resolve(strict=True)
    if not entry_path.is_file() or not entry_path.is_relative_to(root):
        raise ValueError("Web entry must be a file inside the content root.")
    return root, entry_path


def is_web_url_allowed(url: QUrl, content_root: Path):
    scheme = url.scheme().lower()
    if scheme == "about":
        return url.toString() == "about:blank"
    if scheme == "qrc":
        return url.path().startswith("/qtwebchannel/")
    if scheme != "file" or not url.isLocalFile():
        return False

    try:
        requested_path = Path(url.toLocalFile()).resolve(strict=False)
    except (OSError, RuntimeError):
        return False
    return requested_path.is_relative_to(content_root)


class _RestrictedRequestInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, content_root: Path, parent=None):
        super().__init__(parent)
        self._content_root = content_root

    def interceptRequest(self, info):
        if not is_web_url_allowed(info.requestUrl(), self._content_root):
            info.block(True)


class _RestrictedWebPage(QWebEnginePage):
    def __init__(self, profile, content_root: Path, parent=None):
        super().__init__(profile, parent)
        self._content_root = content_root

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        del navigation_type, is_main_frame
        return is_web_url_allowed(url, self._content_root)


class WebPluginHost(QWidget):
    """Embeddable, local-only QtWebEngine host for a plugin web build."""

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

        self.profile = QWebEngineProfile(self)
        self.profile.setHttpCacheType(
            QWebEngineProfile.HttpCacheType.MemoryHttpCache
        )
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies
        )
        self._request_interceptor = _RestrictedRequestInterceptor(
            self.content_root,
            self.profile,
        )
        self.profile.setUrlRequestInterceptor(self._request_interceptor)

        self.page = _RestrictedWebPage(self.profile, self.content_root, self)
        self.view = QWebEngineView(self)
        self.view.setPage(self.page)
        self._configure_settings(self.view.settings())

        self.bridge = WebApiBridge(
            registry,
            owner_id,
            capabilities,
            parent=self,
        )
        self.channel = QWebChannel(self.page)
        self.channel.registerObject("agileApi", self.bridge)
        self.page.setWebChannel(self.channel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.loadFinished.connect(self._on_load_finished)
        if autoload:
            self.load()

    def load(self):
        if self._disposed:
            raise RuntimeError("Web plugin host has been disposed.")
        self.view.setUrl(QUrl.fromLocalFile(str(self.entry_path)))

    @staticmethod
    def _configure_settings(settings: QWebEngineSettings):
        attributes = QWebEngineSettings.WebAttribute
        settings.setAttribute(attributes.JavascriptEnabled, True)
        settings.setAttribute(attributes.JavascriptCanOpenWindows, False)
        settings.setAttribute(attributes.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(attributes.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(attributes.FullScreenSupportEnabled, False)
        settings.setAttribute(attributes.PluginsEnabled, False)

    def _on_load_finished(self, succeeded: bool):
        if self._disposed:
            return
        if succeeded:
            self.load_succeeded.emit()
        else:
            self.load_failed.emit("The local web interface could not be loaded.")

    def dispose(self):
        """Release this host's isolated WebEngine resources exactly once."""
        if self._disposed:
            return
        self._disposed = True

        self.view.loadFinished.disconnect(self._on_load_finished)
        self.view.stop()
        self.channel.deregisterObject(self.bridge)
        self.page.setWebChannel(None)
        self.view.setPage(None)

        self.channel.deleteLater()
        self.bridge.deleteLater()
        self.page.deleteLater()
        self.profile.deleteLater()
        self.view.deleteLater()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
