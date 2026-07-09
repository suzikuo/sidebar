import posixpath
import shlex
import socket
import shutil
import stat as stat_module
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QFileInfo, QDir, QEvent, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QFileSystemModel,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTreeView,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FlowLayout,
    FluentIcon,
    IconWidget,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    RoundMenu,
    SpinBox,
    SubtitleLabel,
    TextEdit,
    ToolButton,
    TransparentToolButton,
)

from core.logger import logger
from ui.components.base_widget import BScrollArea


REMOTE_PREVIEW_MAX_BYTES = 256 * 1024
REMOTE_PREVIEW_MAX_LINES = 200
REMOTE_PREVIEW_ALL_CONFIRM_BYTES = 5 * 1024 * 1024
REMOTE_SEARCH_MAX_MATCHES = 500


REMOTE_TABLE_STYLE = """
    QTableWidget {
        border: none;
        background: transparent;
        gridline-color: transparent;
    }
    QHeaderView::section {
        padding: 4px 8px;
        border: none;
        border-bottom: 1px solid rgba(128, 128, 128, 0.25);
        background: transparent;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 8px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #888;
        min-height: 20px;
        border-radius: 4px;
    }
    QScrollBar::handle:vertical:hover {
        background: #666;
    }
    QScrollBar::handle:vertical:pressed {
        background: #444;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
        background: none;
    }
"""


class SSHConnectionTile(CardWidget):
    """A tile representing an SSH connection."""

    connect_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    scp_requested = Signal(int)

    def __init__(
        self, conn_id, name, host, user, port, remarks="", color=None, parent=None
    ):
        super().__init__(parent)
        self.conn_id = conn_id
        self.setFixedSize(220, 140)
        self.setCursor(Qt.PointingHandCursor)

        self.mainLayout = QHBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        # Color Bar
        if color:
            self.colorBar = QWidget(self)
            self.colorBar.setFixedWidth(5)
            self.colorBar.setStyleSheet(
                f"background-color: {color}; border-top-left-radius: 8px; border-bottom-left-radius: 8px;"
            )
            self.mainLayout.addWidget(self.colorBar)
        else:
            # Add a small placeholder even if no color to keep alignment consistent
            self.colorBar = QWidget(self)
            self.colorBar.setFixedWidth(2)
            self.colorBar.setStyleSheet("background-color: transparent;")
            self.mainLayout.addWidget(self.colorBar)

        # Content Container
        self.contentWidget = QWidget(self)
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setContentsMargins(15, 12, 15, 12)
        self.contentLayout.setSpacing(4)
        self.mainLayout.addWidget(self.contentWidget)

        # Header: Icon + Name
        header_layout = QHBoxLayout()
        icon = IconWidget(FluentIcon.COMMAND_PROMPT, self)
        icon.setFixedSize(20, 20)

        name_label = BodyLabel(name, self)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        header_layout.addWidget(icon)
        header_layout.addWidget(name_label)
        header_layout.addStretch(1)
        self.contentLayout.addLayout(header_layout)

        # Details
        info_label = CaptionLabel(f"{user}@{host}:{port}", self)
        info_label.setStyleSheet("color: rgba(255, 255, 255, 0.6);")
        self.contentLayout.addWidget(info_label)

        if remarks:
            remarks_label = CaptionLabel(remarks, self)
            remarks_label.setStyleSheet(
                "color: rgba(255, 255, 255, 0.4); font-style: italic;"
            )
            remarks_label.setWordWrap(True)
            self.contentLayout.addWidget(remarks_label)

        self.contentLayout.addStretch(1)

        # Connect Button (Bottom Right)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.connect_btn = TransparentToolButton(FluentIcon.SEND, self)
        self.connect_btn.setToolTip("Connect")
        self.connect_btn.clicked.connect(
            lambda: self.connect_requested.emit(self.conn_id)
        )
        btn_layout.addWidget(self.connect_btn)
        self.contentLayout.addLayout(btn_layout)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton:
            # Maybe just open detail or connect? User said "ssh使用windows的命令行 执行ssh命令链接"
            # So clicking should probably connect.
            self.connect_requested.emit(self.conn_id)

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        scp_action = Action(FluentIcon.MOVE, "File Transfer", self)
        edit_action = Action(FluentIcon.EDIT, "Edit", self)
        delete_action = Action(FluentIcon.DELETE, "Delete", self)

        scp_action.triggered.connect(lambda: self.scp_requested.emit(self.conn_id))
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self.conn_id))
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.conn_id)
        )

        menu.addAction(scp_action)
        menu.addSeparator()
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(e.globalPos())


def _format_size(size):
    if size is None:
        return ""

    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{int(size)} B"


def _format_timestamp(timestamp):
    if not timestamp:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _join_remote(parent, name):
    if not parent:
        parent = "."
    if parent == "/":
        return f"/{name}"
    return posixpath.normpath(posixpath.join(parent, name))


class SFTPSession:
    """Keeps one SSH/SFTP connection open for a file transfer dialog."""

    def __init__(self, connection):
        self.connection = connection
        self.client = None
        self.sftp = None

    def ensure_connected(self):
        if self.sftp is not None:
            return

        self.client, self.sftp = self._connect()

    def is_connected(self):
        return self.sftp is not None

    def _connect(self):
        import paramiko

        connect_kwargs = {
            "hostname": self.connection["host"],
            "port": int(self.connection.get("port") or 22),
            "username": self.connection.get("user") or "root",
            "timeout": 20,
            "banner_timeout": 30,
            "auth_timeout": 30,
            "look_for_keys": True,
            "allow_agent": True,
        }

        password = self.connection.get("password")
        if password:
            connect_kwargs["password"] = password
            connect_kwargs["look_for_keys"] = False
            connect_kwargs["allow_agent"] = False

        pem_path = self.connection.get("pem_path")
        if pem_path:
            pem_path = str(pem_path)
            if Path(pem_path).exists():
                if Path(pem_path).suffix.lower() == ".ppk":
                    raise ValueError(
                        "SFTP needs an OpenSSH private key. Convert .ppk to .pem first."
                    )
                connect_kwargs["pkey"] = self._load_private_key(paramiko, pem_path)
                connect_kwargs["look_for_keys"] = False
                connect_kwargs["allow_agent"] = False

        try:
            self._log_connect_kwargs(connect_kwargs)
            client = self._open_paramiko_client(paramiko, connect_kwargs)
        except paramiko.AuthenticationException as original_exc:
            logger.error("Paramiko authentication failed", exc_info=True)
            legacy_kwargs = dict(connect_kwargs)
            legacy_kwargs["disabled_algorithms"] = {
                "pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]
            }
            try:
                logger.info("Retrying Paramiko authentication with legacy RSA signatures")
                client = self._open_paramiko_client(paramiko, legacy_kwargs)
            except Exception:
                logger.error(
                    "Paramiko legacy RSA authentication retry failed",
                    exc_info=True,
                )
                raise original_exc
        except (paramiko.SSHException, socket.timeout) as exc:
            logger.error("Paramiko connection failed", exc_info=True)
            raise

        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(30)

        return client, client.open_sftp()

    def list_dir(self, path):
        self.ensure_connected()
        return self._list_dir(self.sftp, path)

    def upload_many(self, local_paths, remote_dir, progress):
        self.ensure_connected()
        self._upload_many(self.sftp, local_paths, remote_dir, progress)

    def download_many(self, remote_items, local_dir, progress):
        self.ensure_connected()
        self._download_many(self.sftp, remote_items, local_dir, progress)

    def preview_tail(self, remote_item, max_bytes, max_lines):
        self.ensure_connected()
        return self._preview_tail(self.sftp, remote_item, max_bytes, max_lines)

    def preview_before(self, remote_item, before_offset, max_bytes, max_lines):
        self.ensure_connected()
        return self._preview_before(
            self.sftp, remote_item, before_offset, max_bytes, max_lines
        )

    def preview_all(self, remote_item):
        self.ensure_connected()
        return self._preview_all(self.sftp, remote_item)

    def search_remote_file(self, remote_item, query, max_matches):
        self.ensure_connected()
        return self._search_remote_file(remote_item, query, max_matches)

    def close(self):
        if self.sftp is not None:
            try:
                self.sftp.close()
            except Exception:
                pass
            self.sftp = None

        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    @staticmethod
    def _log_connect_kwargs(connect_kwargs):
        safe_kwargs = {}
        for key, value in connect_kwargs.items():
            if key in {"password", "pkey"}:
                safe_kwargs[key] = "<set>"
            else:
                safe_kwargs[key] = value
        logger.debug("Paramiko connect kwargs: %s", safe_kwargs)

    @staticmethod
    def _load_private_key(paramiko, pem_path):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import ec, rsa

            with open(pem_path, "rb") as key_file:
                crypto_key = serialization.load_pem_private_key(
                    key_file.read(), password=None
                )

            if isinstance(crypto_key, rsa.RSAPrivateKey):
                logger.debug("Loaded PKCS#8 SSH private key as RSAKey")
                return paramiko.RSAKey(key=crypto_key)

            if isinstance(crypto_key, ec.EllipticCurvePrivateKey):
                logger.debug("Loaded PKCS#8 SSH private key as ECDSAKey")
                return paramiko.ECDSAKey(
                    vals=(crypto_key, crypto_key.public_key())
                )
        except Exception:
            logger.error("Cryptography PKCS#8 private key load failed", exc_info=True)

        try:
            key = paramiko.PKey.from_path(pem_path)
            logger.debug("Loaded SSH private key with Paramiko PKey.from_path")
            return key
        except Exception:
            logger.error("Paramiko PKey.from_path failed", exc_info=True)

        errors = []
        for key_cls in (paramiko.RSAKey, paramiko.ECDSAKey, paramiko.Ed25519Key):
            try:
                key = key_cls.from_private_key_file(pem_path)
                logger.debug("Loaded SSH private key as %s", key_cls.__name__)
                return key
            except Exception as exc:
                errors.append(f"{key_cls.__name__}: {exc}")

        raise ValueError("Could not load private key. " + "; ".join(errors))

    @staticmethod
    def _open_paramiko_client(paramiko, connect_kwargs):
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(**connect_kwargs)
        except Exception:
            client.close()
            raise
        return client

    def _list_dir(self, sftp, path):
        normalized_path = sftp.normalize(path or ".")
        entries = []

        for attr in sftp.listdir_attr(normalized_path):
            if attr.filename in (".", ".."):
                continue

            is_dir = stat_module.S_ISDIR(attr.st_mode)
            entries.append(
                {
                    "name": attr.filename,
                    "path": _join_remote(normalized_path, attr.filename),
                    "is_dir": is_dir,
                    "size": None if is_dir else attr.st_size,
                    "mtime": attr.st_mtime,
                }
            )

        entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
        return {"path": normalized_path, "entries": entries}

    def _upload_many(self, sftp, local_paths, remote_dir, progress):
        remote_dir = sftp.normalize(remote_dir or ".")
        for local_path in local_paths:
            source = Path(local_path)
            if not source.exists():
                raise FileNotFoundError(str(source))

            target = _join_remote(remote_dir, source.name)
            self._upload_path(sftp, source, target, progress)

    def _upload_path(self, sftp, source, remote_path, progress):
        if source.is_dir():
            self._mkdir_p(sftp, remote_path)
            for child in source.iterdir():
                self._upload_path(
                    sftp, child, _join_remote(remote_path, child.name), progress
                )
            return

        progress(f"Uploading {source.name}", 0)
        sftp.put(
            str(source),
            remote_path,
            callback=lambda done, total: self._emit_file_progress(
                f"Uploading {source.name}", done, total, progress
            ),
        )

    def _download_many(self, sftp, remote_items, local_dir, progress):
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        for item in remote_items:
            remote_path = item["path"]
            target = local_dir / item["name"]
            self._download_path(
                sftp, remote_path, target, item.get("is_dir"), progress
            )

    def _download_path(
        self, sftp, remote_path, local_path, known_is_dir=None, progress=None
    ):
        is_dir = known_is_dir
        if is_dir is None:
            is_dir = stat_module.S_ISDIR(sftp.stat(remote_path).st_mode)

        if is_dir:
            local_path.mkdir(parents=True, exist_ok=True)
            for attr in sftp.listdir_attr(remote_path):
                if attr.filename in (".", ".."):
                    continue
                child_remote = _join_remote(remote_path, attr.filename)
                child_local = local_path / attr.filename
                child_is_dir = stat_module.S_ISDIR(attr.st_mode)
                self._download_path(
                    sftp, child_remote, child_local, child_is_dir, progress
                )
            return

        local_path.parent.mkdir(parents=True, exist_ok=True)
        progress(f"Downloading {local_path.name}", 0)
        sftp.get(
            remote_path,
            str(local_path),
            callback=lambda done, total: self._emit_file_progress(
                f"Downloading {local_path.name}", done, total, progress
            ),
        )

    def _preview_tail(self, sftp, remote_item, max_bytes, max_lines):
        if remote_item.get("is_dir"):
            raise ValueError("Folders cannot be previewed")

        attr = sftp.stat(remote_item["path"])
        size = attr.st_size or 0
        offset = max(0, size - max_bytes)

        return self._preview_chunk(
            sftp,
            remote_item,
            size,
            offset,
            size,
            max_lines,
            mode="tail",
            full_file=False,
        )

    def _preview_before(self, sftp, remote_item, before_offset, max_bytes, max_lines):
        if remote_item.get("is_dir"):
            raise ValueError("Folders cannot be previewed")

        attr = sftp.stat(remote_item["path"])
        size = attr.st_size or 0
        end = max(0, min(before_offset, size))
        start = max(0, end - max_bytes)

        return self._preview_chunk(
            sftp,
            remote_item,
            size,
            start,
            end,
            max_lines,
            mode="before",
            full_file=False,
        )

    def _preview_all(self, sftp, remote_item):
        if remote_item.get("is_dir"):
            raise ValueError("Folders cannot be previewed")

        attr = sftp.stat(remote_item["path"])
        size = attr.st_size or 0
        return self._preview_chunk(
            sftp,
            remote_item,
            size,
            0,
            size,
            None,
            mode="all",
            full_file=True,
        )

    def _preview_chunk(
        self,
        sftp,
        remote_item,
        size,
        start,
        end,
        max_lines=None,
        mode="tail",
        full_file=False,
    ):
        remote_path = remote_item["path"]
        length = max(0, end - start)
        with sftp.open(remote_path, "rb") as remote_file:
            if start:
                remote_file.seek(start)
            content = remote_file.read(length)

        lines_truncated = False
        preview_bytes = content
        if max_lines:
            lines = content.splitlines(keepends=True)
            if len(lines) > max_lines:
                skipped = sum(len(line) for line in lines[:-max_lines])
                start += skipped
                lines = lines[-max_lines:]
                lines_truncated = True
            preview_bytes = b"".join(lines)

        text = preview_bytes.decode("utf-8", errors="replace")
        return {
            "name": remote_item["name"],
            "path": remote_path,
            "size": size,
            "start": start,
            "end": end,
            "max_bytes": length,
            "max_lines": max_lines,
            "has_more_before": start > 0,
            "lines_truncated": lines_truncated,
            "mode": mode,
            "full_file": full_file,
            "text": text,
        }

    def _search_remote_file(self, remote_item, query, max_matches):
        if remote_item.get("is_dir"):
            raise ValueError("Folders cannot be searched")

        if not query:
            raise ValueError("Search text is empty")

        remote_path = remote_item["path"]
        command = (
            f"grep -n -I -F -m {int(max_matches)} -- "
            f"{shlex.quote(query)} {shlex.quote(remote_path)}"
        )
        stdin, stdout, stderr = self.client.exec_command(command, timeout=60)
        stdin.close()

        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace").strip()
        exit_status = stdout.channel.recv_exit_status()

        if exit_status not in (0, 1):
            raise RuntimeError(err or f"Remote grep failed with exit code {exit_status}")

        lines = out.splitlines()
        return {
            "name": remote_item["name"],
            "path": remote_path,
            "query": query,
            "matches": lines,
            "match_count": len(lines),
            "max_matches": max_matches,
            "truncated": len(lines) >= max_matches,
        }

    def _mkdir_p(self, sftp, remote_path):
        path = posixpath.normpath(remote_path)
        if path in ("", "."):
            return

        parts = [part for part in path.split("/") if part]
        current = "/" if path.startswith("/") else ""
        for part in parts:
            current = _join_remote(current or ".", part)
            try:
                sftp.stat(current)
            except OSError:
                sftp.mkdir(current)

    def _emit_file_progress(self, label, done, total, progress):
        percent = 0
        if total:
            percent = max(0, min(100, int(done * 100 / total)))
        progress(label, percent)


class SFTPTaskThread(QThread):
    """Runs SFTP work off the UI thread."""

    result = Signal(str, object)
    progress = Signal(str, int)
    error = Signal(str)

    def __init__(self, session, action, payload=None, parent=None):
        super().__init__(parent)
        self.session = session
        self.action = action
        self.payload = payload or {}

    def run(self):
        try:
            had_connection = self.session.is_connected()
            try:
                self._run_action()
            except (OSError, EOFError):
                if not had_connection:
                    raise

                logger.info("SFTP session dropped; reconnecting once")
                self.session.close()
                self._run_action()
        except ImportError:
            self.error.emit(
                "Missing dependency: install paramiko to use visual file transfer."
            )
        except Exception as exc:
            trace = traceback.format_exc()
            logger.error("SFTP transfer task failed:\n%s", trace, exc_info=True)
            self.error.emit(
                f"{exc}\n\nFull Paramiko traceback was written to the console and app.log."
            )

    def _run_action(self):
        if self.action == "list":
            path = self.payload.get("path") or "."
            self.result.emit("list", self.session.list_dir(path))
        elif self.action == "upload":
            self.session.upload_many(
                self.payload.get("local_paths", []),
                self.payload.get("remote_dir") or ".",
                self.progress.emit,
            )
            self.result.emit("transfer", {"direction": "upload"})
        elif self.action == "download":
            self.session.download_many(
                self.payload.get("remote_items", []),
                Path(self.payload.get("local_dir") or Path.home()),
                self.progress.emit,
            )
            self.result.emit("transfer", {"direction": "download"})
        elif self.action == "preview":
            item = self.payload["remote_item"]
            self.result.emit(
                "preview",
                self.session.preview_tail(
                    item,
                    self.payload.get("max_bytes") or REMOTE_PREVIEW_MAX_BYTES,
                    self.payload.get("max_lines") or REMOTE_PREVIEW_MAX_LINES,
                ),
            )
        elif self.action == "preview_before":
            item = self.payload["remote_item"]
            self.result.emit(
                "preview_before",
                self.session.preview_before(
                    item,
                    self.payload.get("before_offset") or 0,
                    self.payload.get("max_bytes") or REMOTE_PREVIEW_MAX_BYTES,
                    self.payload.get("max_lines") or REMOTE_PREVIEW_MAX_LINES,
                ),
            )
        elif self.action == "preview_all":
            self.result.emit(
                "preview_all",
                self.session.preview_all(self.payload["remote_item"]),
            )
        elif self.action == "remote_search":
            self.result.emit(
                "remote_search",
                self.session.search_remote_file(
                    self.payload["remote_item"],
                    self.payload.get("query") or "",
                    self.payload.get("max_matches") or REMOTE_SEARCH_MAX_MATCHES,
                ),
            )


class RemotePreviewDialog(QDialog):
    """Shows a lazy, read-only preview of one remote file."""

    def __init__(self, preview, session, remote_item, parent=None):
        super().__init__(parent)
        self.session = session
        self.remote_item = dict(remote_item)
        self.worker = None
        self.preview = dict(preview)
        self.loaded_start = preview.get("start", 0)
        self.loaded_end = preview.get("end", preview.get("size", 0))
        self.has_more_before = preview.get("has_more_before", False)
        self.loading_preview = False
        self.ignore_scroll_load = False
        self.pending_before_offset = None
        self.last_scroll_value = 0
        self.user_scroll_pending = False

        self.setWindowTitle(f"Preview - {preview['name']}")
        self.resize(820, 560)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = SubtitleLabel(preview["name"], self)
        path_label = CaptionLabel(preview["path"], self)
        path_label.setWordWrap(True)

        self.metaLabel = CaptionLabel("", self)

        search_row = QHBoxLayout()
        self.searchInput = LineEdit(self)
        self.searchInput.setPlaceholderText("Search text")
        self.searchInput.returnPressed.connect(self._find_next)
        self.findPrevBtn = ToolButton(FluentIcon.UP, self)
        self.findPrevBtn.setToolTip("Previous match")
        self.findPrevBtn.clicked.connect(self._find_previous)
        self.findNextBtn = ToolButton(FluentIcon.DOWN, self)
        self.findNextBtn.setToolTip("Next loaded match")
        self.findNextBtn.clicked.connect(self._find_next)
        self.remoteSearchBtn = PushButton(FluentIcon.SEARCH, "Remote Search", self)
        self.remoteSearchBtn.setToolTip("Search the full remote file on the server")
        self.remoteSearchBtn.clicked.connect(self._remote_search)
        search_row.addWidget(self.searchInput, 1)
        search_row.addWidget(self.findPrevBtn)
        search_row.addWidget(self.findNextBtn)
        search_row.addWidget(self.remoteSearchBtn)

        self.textEdit = QPlainTextEdit(self)
        self.textEdit.setReadOnly(True)
        self.textEdit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.textEdit.setPlainText(preview["text"])
        self.textEdit.moveCursor(QTextCursor.End)
        scrollbar = self.textEdit.verticalScrollBar()
        self.last_scroll_value = scrollbar.value()
        scrollbar.valueChanged.connect(self._on_scroll)
        self.textEdit.viewport().installEventFilter(self)
        scrollbar.installEventFilter(self)

        self.loadAllBtn = PushButton(FluentIcon.DOCUMENT, "Load All", self)
        self.loadAllBtn.clicked.connect(self._load_all)
        close_btn = PushButton("Close", self)
        close_btn.clicked.connect(self.close)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(self.loadAllBtn)
        button_row.addWidget(close_btn)

        layout.addWidget(title)
        layout.addWidget(path_label)
        layout.addWidget(self.metaLabel)
        layout.addLayout(search_row)
        layout.addWidget(self.textEdit, 1)
        layout.addLayout(button_row)
        self._update_meta()

    def _on_scroll(self, value):
        previous_value = self.last_scroll_value
        self.last_scroll_value = value
        scrollbar = self.textEdit.verticalScrollBar()
        if (
            value == 0
            and previous_value > 0
            and scrollbar.maximum() > 0
            and self.user_scroll_pending
            and self.has_more_before
            and not self.loading_preview
            and not self.ignore_scroll_load
        ):
            self.user_scroll_pending = False
            self._load_before()
        elif value != 0:
            self.user_scroll_pending = False

    def eventFilter(self, watched, event):
        if watched in (self.textEdit.viewport(), self.textEdit.verticalScrollBar()):
            if event.type() in (
                QEvent.Wheel,
                QEvent.MouseButtonPress,
                QEvent.KeyPress,
            ):
                self.user_scroll_pending = True
        return super().eventFilter(watched, event)

    def _load_before(self):
        if self.loading_preview or (self.worker and self.worker.isRunning()):
            return

        before_offset = self.loaded_start
        self.pending_before_offset = before_offset
        self.has_more_before = False
        self._set_loading(True)
        self.worker = SFTPTaskThread(
            self.session,
            "preview_before",
            {
                "remote_item": self.remote_item,
                "before_offset": before_offset,
                "max_bytes": REMOTE_PREVIEW_MAX_BYTES,
                "max_lines": REMOTE_PREVIEW_MAX_LINES,
            },
            self,
        )
        self.worker.result.connect(self._on_task_result)
        self.worker.error.connect(self._on_task_error)
        self.worker.finished.connect(lambda: self._set_loading(False))
        self.worker.start()

    def _load_all(self):
        if self.loading_preview or (self.worker and self.worker.isRunning()):
            return

        size = self.preview.get("size", 0)
        if size >= REMOTE_PREVIEW_ALL_CONFIRM_BYTES:
            result = QMessageBox.question(
                self,
                "Load full file?",
                f"This file is {_format_size(size)}. Load the full content?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                return

        self._set_loading(True)
        self.worker = SFTPTaskThread(
            self.session,
            "preview_all",
            {"remote_item": self.remote_item},
            self,
        )
        self.worker.result.connect(self._on_task_result)
        self.worker.error.connect(self._on_task_error)
        self.worker.finished.connect(lambda: self._set_loading(False))
        self.worker.start()

    def _on_task_result(self, result_type, data):
        if result_type == "preview_before":
            self._prepend_preview(data)
        elif result_type == "preview_all":
            self._replace_preview(data)
        elif result_type == "remote_search":
            self._show_remote_search_results(data)

    def _prepend_preview(self, data):
        previous_start = self.loaded_start
        previous_scrollbar = self.textEdit.verticalScrollBar()
        previous_maximum = previous_scrollbar.maximum()
        previous_value = previous_scrollbar.value()

        current_text = self.textEdit.toPlainText()
        prefix = data["text"]
        separator = "" if not prefix or not current_text else "\n"
        self.ignore_scroll_load = True
        self.textEdit.blockSignals(True)
        self.textEdit.setPlainText(prefix + separator + current_text)

        new_maximum = previous_scrollbar.maximum()
        previous_scrollbar.setValue(previous_value + (new_maximum - previous_maximum))
        self.last_scroll_value = previous_scrollbar.value()
        self.textEdit.blockSignals(False)
        self.ignore_scroll_load = False

        self.loaded_start = data.get("start", self.loaded_start)
        made_progress = self.loaded_start < previous_start
        self.has_more_before = made_progress and data.get("has_more_before", False)
        self.pending_before_offset = None
        self.preview.update(data)
        self._update_meta()

    def _replace_preview(self, data):
        self.ignore_scroll_load = True
        self.textEdit.blockSignals(True)
        self.textEdit.setPlainText(data["text"])
        self.loaded_start = data.get("start", 0)
        self.loaded_end = data.get("end", data.get("size", 0))
        self.has_more_before = False
        self.pending_before_offset = None
        self.preview.update(data)
        self.textEdit.moveCursor(QTextCursor.End)
        self.last_scroll_value = self.textEdit.verticalScrollBar().value()
        self.textEdit.blockSignals(False)
        self.ignore_scroll_load = False
        self._update_meta()

    def _on_task_error(self, message):
        if self.pending_before_offset is not None:
            self.has_more_before = self.loaded_start > 0
            self.pending_before_offset = None
        InfoBar.error("Preview", message, duration=5000, parent=self.window())

    def _find_next(self):
        self._find_text(backward=False)

    def _find_previous(self):
        self._find_text(backward=True)

    def _find_text(self, backward=False):
        query = self.searchInput.text()
        if not query:
            return

        flags = QTextDocument.FindFlags()
        if backward:
            flags |= QTextDocument.FindBackward

        if self.textEdit.find(query, flags):
            self._update_meta()
            return

        cursor = self.textEdit.textCursor()
        cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
        self.textEdit.setTextCursor(cursor)
        if self.textEdit.find(query, flags):
            self._update_meta()
            return

        self.metaLabel.setText(f"No match in loaded content: {query}")

    def _remote_search(self):
        query = self.searchInput.text()
        if not query:
            return

        if self.loading_preview or (self.worker and self.worker.isRunning()):
            return

        self._set_loading(True, "Searching remote file...")
        self.worker = SFTPTaskThread(
            self.session,
            "remote_search",
            {
                "remote_item": self.remote_item,
                "query": query,
                "max_matches": REMOTE_SEARCH_MAX_MATCHES,
            },
            self,
        )
        self.worker.result.connect(self._on_task_result)
        self.worker.error.connect(self._on_task_error)
        self.worker.finished.connect(lambda: self._set_loading(False))
        self.worker.start()

    def _show_remote_search_results(self, data):
        matches = data.get("matches", [])
        header = (
            f"Remote search for {data['query']!r} in {data['path']}\n"
            f"{data['match_count']} match(es)"
        )
        if data.get("truncated"):
            header += f" shown, stopped at first {data['max_matches']} matches"
        text = header + "\n\n" + "\n".join(matches)

        self.ignore_scroll_load = True
        self.textEdit.blockSignals(True)
        self.textEdit.setPlainText(text)
        self.textEdit.moveCursor(QTextCursor.Start)
        self.last_scroll_value = self.textEdit.verticalScrollBar().value()
        self.textEdit.blockSignals(False)
        self.ignore_scroll_load = False
        self.has_more_before = False
        self.pending_before_offset = None
        self.metaLabel.setText(header.replace("\n", " | "))

    def _set_loading(self, loading, message=None):
        self.loading_preview = loading
        self.loadAllBtn.setEnabled(not loading)
        self.findPrevBtn.setEnabled(not loading)
        self.findNextBtn.setEnabled(not loading)
        self.searchInput.setEnabled(not loading)
        self.remoteSearchBtn.setEnabled(not loading)
        self.metaLabel.setText(message or "Loading..." if loading else self._meta_text())

    def _update_meta(self):
        self.metaLabel.setText(self._meta_text())

    def _meta_text(self):
        size = self.preview.get("size", 0)
        if self.preview.get("full_file"):
            return f"{_format_size(size)} | full file loaded"

        loaded = max(0, self.loaded_end - self.loaded_start)
        notes = [
            f"loaded {_format_size(loaded)}",
            f"showing up to {REMOTE_PREVIEW_MAX_LINES} lines per chunk",
        ]
        if self.has_more_before:
            notes.append("scroll to top for older content")
        return f"{_format_size(size)} | " + " | ".join(notes)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            InfoBar.info(
                "Preview",
                "Wait for the current preview load to finish",
                parent=self.window(),
            )
            event.ignore()
            return
        super().closeEvent(event)


class SFTPBrowserDialog(QDialog):
    """A compact two-pane SFTP file manager."""

    def __init__(self, parent=None, connection=None, keys_dir=None):
        super().__init__(parent)
        self.connection = dict(connection or {})
        self.keys_dir = Path(keys_dir) if keys_dir else Path(__file__).parent / "keys"
        self.session = None
        self.worker = None
        self._refresh_after_task = False
        self._current_task = None
        self.remote_path = "."
        self.remoteDirCache = {}
        self.remoteCacheOrder = []
        self.remoteCacheLimit = 80
        self.iconProvider = QFileIconProvider()
        self.remoteFolderIcon = self.iconProvider.icon(QFileIconProvider.Folder)
        self.remoteIconCache = {}
        self.blankIcon = QIcon()

        self._resolve_key_path()
        self.session = SFTPSession(self.connection)
        self._setup_ui()
        self._load_remote(".")

    def _setup_ui(self):
        conn_name = self.connection.get("name") or self.connection.get("host") or "SSH"
        self.setWindowTitle(f"File Transfer - {conn_name}")
        self.resize(980, 640)
        self.setMinimumSize(760, 500)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(10)

        header = QHBoxLayout()
        title = SubtitleLabel(f"File Transfer - {conn_name}", self)
        detail = CaptionLabel(
            f"{self.connection.get('user', 'root')}@{self.connection.get('host')}:{self.connection.get('port', 22)}",
            self,
        )
        header_text = QVBoxLayout()
        header_text.addWidget(title)
        header_text.addWidget(detail)
        header.addLayout(header_text)
        header.addStretch(1)

        self.refreshBtn = ToolButton(FluentIcon.SYNC, self)
        self.refreshBtn.setToolTip("Refresh remote")
        self.refreshBtn.clicked.connect(
            lambda: self._load_remote(self.remote_path, force_refresh=True)
        )
        self.closeBtn = PushButton("Close", self)
        self.closeBtn.clicked.connect(self.close)
        header.addWidget(self.refreshBtn)
        header.addWidget(self.closeBtn)
        root_layout.addLayout(header)

        panes = QHBoxLayout()
        panes.setSpacing(12)
        panes.addWidget(self._create_local_panel(), 1)

        divider = QFrame(self)
        divider.setFrameShape(QFrame.VLine)
        divider.setFrameShadow(QFrame.Sunken)
        panes.addWidget(divider)

        panes.addWidget(self._create_remote_panel(), 1)
        root_layout.addLayout(panes, 1)

        progress_row = QHBoxLayout()
        self.statusLabel = CaptionLabel("Ready", self)
        self.progressBar = QProgressBar(self)
        self.progressBar.setRange(0, 100)
        self.progressBar.setValue(0)
        progress_row.addWidget(self.statusLabel)
        progress_row.addWidget(self.progressBar, 1)
        root_layout.addLayout(progress_row)

        self.refreshShortcut = QShortcut(QKeySequence("F5"), self)
        self.refreshShortcut.activated.connect(
            lambda: self._load_remote(self.remote_path, force_refresh=True)
        )

    def _create_local_panel(self):
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.addWidget(BodyLabel("Local", self))
        title_row.addStretch(1)
        self.uploadBtn = PrimaryPushButton(FluentIcon.UP, "Upload", self)
        self.uploadBtn.setToolTip("Upload selected local files or folders")
        self.uploadBtn.clicked.connect(self._upload_selected)
        self.localUpBtn = ToolButton(FluentIcon.UP, self)
        self.localUpBtn.setToolTip("Parent folder")
        self.localUpBtn.clicked.connect(self._go_local_parent)
        self.localChooseBtn = ToolButton(FluentIcon.FOLDER, self)
        self.localChooseBtn.setToolTip("Choose local folder")
        self.localChooseBtn.clicked.connect(self._choose_local_root)
        title_row.addWidget(self.uploadBtn)
        title_row.addWidget(self.localUpBtn)
        title_row.addWidget(self.localChooseBtn)
        layout.addLayout(title_row)

        self.localPathInput = LineEdit(self)
        self.localPathInput.setReadOnly(True)
        layout.addWidget(self.localPathInput)

        self.localModel = QFileSystemModel(self)
        self.localModel.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot)
        start_path = str(Path.home())
        self.localModel.setRootPath(start_path)

        self.localTree = QTreeView(self)
        self.localTree.setModel(self.localModel)
        self.localTree.setRootIndex(self.localModel.index(start_path))
        self.localTree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.localTree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.localTree.setSortingEnabled(True)
        self.localTree.sortByColumn(0, Qt.AscendingOrder)
        self.localTree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.localTree.setColumnWidth(0, 260)
        self.localTree.doubleClicked.connect(self._on_local_double_clicked)
        layout.addWidget(self.localTree, 1)

        self._set_local_root(start_path)
        return panel

    def _create_remote_panel(self):
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.addWidget(BodyLabel("Remote", self))
        title_row.addStretch(1)
        self.previewBtn = PrimaryPushButton(FluentIcon.VIEW, "Preview", self)
        self.previewBtn.setToolTip("Preview the tail of one selected remote file")
        self.previewBtn.clicked.connect(self._preview_selected)
        self.downloadBtn = PrimaryPushButton(FluentIcon.DOWNLOAD, "Download", self)
        self.downloadBtn.setToolTip("Download selected remote files or folders")
        self.downloadBtn.clicked.connect(self._download_selected)
        self.remoteHomeBtn = ToolButton(FluentIcon.HOME, self)
        self.remoteHomeBtn.setToolTip("Home")
        self.remoteHomeBtn.clicked.connect(lambda: self._load_remote("."))
        self.remoteUpBtn = ToolButton(FluentIcon.UP, self)
        self.remoteUpBtn.setToolTip("Parent folder")
        self.remoteUpBtn.clicked.connect(self._go_remote_parent)
        title_row.addWidget(self.previewBtn)
        title_row.addWidget(self.downloadBtn)
        title_row.addWidget(self.remoteHomeBtn)
        title_row.addWidget(self.remoteUpBtn)
        layout.addLayout(title_row)

        self.remotePathInput = LineEdit(self)
        self.remotePathInput.setPlaceholderText("Remote path")
        self.remotePathInput.returnPressed.connect(
            lambda: self._load_remote(self.remotePathInput.text().strip() or ".")
        )
        layout.addWidget(self.remotePathInput)

        self.remoteTable = QTableWidget(self)
        self.remoteTable.setColumnCount(4)
        self.remoteTable.setHorizontalHeaderLabels(["Name", "Size", "Modified", "Type"])
        self.remoteTable.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.remoteTable.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.remoteTable.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.remoteTable.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.remoteTable.verticalHeader().hide()
        self.remoteTable.verticalHeader().setDefaultSectionSize(28)
        self.remoteTable.setIconSize(QSize(16, 16))
        self.remoteTable.setShowGrid(False)
        self.remoteTable.setWordWrap(False)
        self.remoteTable.setFrameShape(QFrame.NoFrame)
        self.remoteTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.remoteTable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.remoteTable.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.remoteTable.setVerticalScrollMode(QAbstractItemView.ScrollPerItem)
        self.remoteTable.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.remoteTable.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.remoteTable.setStyleSheet(REMOTE_TABLE_STYLE)
        self.remoteTable.cellDoubleClicked.connect(self._on_remote_double_clicked)
        layout.addWidget(self.remoteTable, 1)
        return panel

    def _resolve_key_path(self):
        pem_path = self.connection.get("pem_path")
        if pem_path and not Path(str(pem_path)).is_absolute():
            candidate = self.keys_dir / str(pem_path)
            if candidate.exists():
                self.connection["pem_path"] = str(candidate)

    def _set_local_root(self, path):
        path = str(Path(path))
        self.localPathInput.setText(path)
        self.localTree.setRootIndex(self.localModel.index(path))

    def _choose_local_root(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Local Folder", self.localPathInput.text()
        )
        if path:
            self._set_local_root(path)

    def _on_local_double_clicked(self, index):
        if self.localModel.isDir(index):
            self._set_local_root(self.localModel.filePath(index))

    def _go_local_parent(self):
        current = Path(self.localPathInput.text())
        parent = current.parent
        if parent != current:
            self._set_local_root(parent)

    def _go_remote_parent(self):
        current = self.remote_path.rstrip("/") or "/"
        if current == "/":
            self._load_remote("/")
            return
        parent = posixpath.dirname(current) or "/"
        self._load_remote(parent)

    def _on_remote_double_clicked(self, row, _column):
        item = self.remoteTable.item(row, 0)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if data and data.get("is_dir"):
            self._load_remote(data["path"])

    def _selected_local_paths(self):
        paths = []
        seen = set()
        for index in self.localTree.selectionModel().selectedRows(0):
            path = self.localModel.filePath(index)
            if path and path not in seen:
                paths.append(path)
                seen.add(path)
        return paths

    def _selected_remote_items(self):
        items = []
        for index in self.remoteTable.selectionModel().selectedRows(0):
            table_item = self.remoteTable.item(index.row(), 0)
            if table_item:
                data = table_item.data(Qt.UserRole)
                if data:
                    items.append(data)
        return items

    def _upload_selected(self):
        local_paths = self._selected_local_paths()
        if not local_paths:
            InfoBar.warning(
                "Upload",
                "Select local files or folders first",
                parent=self.window(),
            )
            return
        self._start_task(
            "upload",
            {"local_paths": local_paths, "remote_dir": self.remote_path},
            "Uploading...",
        )

    def _download_selected(self):
        remote_items = self._selected_remote_items()
        if not remote_items:
            InfoBar.warning(
                "Download",
                "Select remote files or folders first",
                parent=self.window(),
            )
            return
        self._start_task(
            "download",
            {"remote_items": remote_items, "local_dir": self.localPathInput.text()},
            "Downloading...",
        )

    def _preview_selected(self):
        remote_items = self._selected_remote_items()
        if len(remote_items) != 1:
            InfoBar.warning(
                "Preview",
                "Select one remote file first",
                parent=self.window(),
            )
            return

        item = remote_items[0]
        if item.get("is_dir"):
            InfoBar.warning(
                "Preview",
                "Folders cannot be previewed",
                parent=self.window(),
            )
            return

        self._start_task(
            "preview",
            {
                "remote_item": item,
                "max_bytes": REMOTE_PREVIEW_MAX_BYTES,
                "max_lines": REMOTE_PREVIEW_MAX_LINES,
            },
            "Loading preview...",
        )

    def _load_remote(self, path, force_refresh=False):
        cache_key = self._remote_cache_key(path)
        if not force_refresh and cache_key in self.remoteDirCache:
            self._show_remote_entries(self.remoteDirCache[cache_key])
            self.statusLabel.setText("Ready")
            self.progressBar.setValue(0)
            return

        self._start_task("list", {"path": path}, "Loading remote...")

    def _start_task(self, action, payload, status):
        if self.worker and self.worker.isRunning():
            InfoBar.info(
                "Busy",
                "A transfer task is still running",
                parent=self.window(),
            )
            return

        self.statusLabel.setText(status)
        self.progressBar.setValue(0)
        self._set_busy(True)
        self._current_task = (action, payload, status)

        self.worker = SFTPTaskThread(self.session, action, payload, self)
        self.worker.result.connect(self._on_task_result)
        self.worker.progress.connect(self._on_task_progress)
        self.worker.error.connect(self._on_task_error)
        self.worker.finished.connect(self._on_task_finished)
        self.worker.start()

    def _on_task_result(self, result_type, data):
        if result_type == "list":
            self._cache_remote_entries(data)
            self._show_remote_entries(data)
            self.statusLabel.setText("Ready")
            self.progressBar.setValue(0)
            return

        if result_type == "preview":
            self.statusLabel.setText("Preview ready")
            self.progressBar.setValue(100)
            _action, payload, _status = self._current_task
            dialog = RemotePreviewDialog(data, self.session, payload["remote_item"], self)
            dialog.exec()
            self.statusLabel.setText("Ready")
            self.progressBar.setValue(0)
            return

        self.statusLabel.setText("Transfer complete")
        self.progressBar.setValue(100)
        self._invalidate_remote_cache(self.remote_path)
        self._refresh_after_task = True
        InfoBar.success("Transfer", "Done", duration=2000, parent=self.window())

    def _on_task_progress(self, label, percent):
        self.statusLabel.setText(label)
        self.progressBar.setValue(percent)

    def _on_task_error(self, message):
        self.statusLabel.setText("Error")
        self.progressBar.setValue(0)
        InfoBar.error("SFTP", message, duration=5000, parent=self.window())

    def _on_task_finished(self):
        self._set_busy(False)
        if self._refresh_after_task:
            self._refresh_after_task = False
            self._load_remote(self.remote_path, force_refresh=True)

    def _show_remote_entries(self, data):
        self.remote_path = data["path"]
        self.remotePathInput.setText(self.remote_path)
        entries = data["entries"]

        self.remoteTable.setUpdatesEnabled(False)
        self.remoteTable.setSortingEnabled(False)
        self.remoteTable.clearContents()
        self.remoteTable.setRowCount(len(entries))
        try:
            for row, entry in enumerate(entries):
                name_item = QTableWidgetItem(entry["name"])
                icon = self._remote_icon(entry)
                if not icon.isNull():
                    name_item.setIcon(icon)
                name_item.setData(Qt.UserRole, entry)

                size_item = QTableWidgetItem(
                    "" if entry["is_dir"] else _format_size(entry["size"])
                )
                modified_item = QTableWidgetItem(_format_timestamp(entry["mtime"]))
                type_item = QTableWidgetItem("Folder" if entry["is_dir"] else "File")

                self.remoteTable.setItem(row, 0, name_item)
                self.remoteTable.setItem(row, 1, size_item)
                self.remoteTable.setItem(row, 2, modified_item)
                self.remoteTable.setItem(row, 3, type_item)
        finally:
            self.remoteTable.setUpdatesEnabled(True)

    def _cache_remote_entries(self, data):
        key = self._remote_cache_key(data["path"])
        self.remoteDirCache[key] = data

        if key in self.remoteCacheOrder:
            self.remoteCacheOrder.remove(key)
        self.remoteCacheOrder.append(key)

        while len(self.remoteCacheOrder) > self.remoteCacheLimit:
            stale_key = self.remoteCacheOrder.pop(0)
            self.remoteDirCache.pop(stale_key, None)

    def _invalidate_remote_cache(self, path=None):
        if path is None:
            self.remoteDirCache.clear()
            self.remoteCacheOrder.clear()
            return

        key = self._remote_cache_key(path)
        self.remoteDirCache.pop(key, None)
        if key in self.remoteCacheOrder:
            self.remoteCacheOrder.remove(key)

    @staticmethod
    def _remote_cache_key(path):
        return posixpath.normpath(path or ".")

    def _remote_icon(self, entry):
        if entry["is_dir"]:
            return self.remoteFolderIcon

        suffix = Path(entry["name"]).suffix
        if not suffix:
            return self.blankIcon

        suffix = suffix.lower()
        if suffix in self.remoteIconCache:
            return self.remoteIconCache[suffix]

        icon = self.iconProvider.icon(QFileInfo(f"remote{suffix}"))
        icon = icon if not icon.isNull() else self.blankIcon
        self.remoteIconCache[suffix] = icon
        return icon

    def _set_busy(self, busy):
        self.refreshBtn.setEnabled(not busy)
        self.localUpBtn.setEnabled(not busy)
        self.localChooseBtn.setEnabled(not busy)
        self.remoteHomeBtn.setEnabled(not busy)
        self.remoteUpBtn.setEnabled(not busy)
        self.uploadBtn.setEnabled(not busy)
        self.previewBtn.setEnabled(not busy)
        self.downloadBtn.setEnabled(not busy)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            InfoBar.info(
                "Busy",
                "Wait for the current transfer to finish",
                parent=self.window(),
            )
            event.ignore()
            return
        if self.session is not None:
            self.session.close()
        self._invalidate_remote_cache()
        self.remoteIconCache.clear()
        super().closeEvent(event)


class SSHConnectionDialog(MessageBoxBase):
    """Dialog to add or edit an SSH connection."""

    def __init__(self, parent=None, data=None, keys_dir=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("SSH Connection Settings", self)

        # Path for backing up keys - passed from plugin/widget
        self._keys_dir = Path(keys_dir) if keys_dir else Path(__file__).parent / "keys"
        if not self._keys_dir.exists():
            self._keys_dir.mkdir(parents=True, exist_ok=True)

        self.nameInput = LineEdit(self)
        self.hostInput = LineEdit(self)
        self.userInput = LineEdit(self)
        self.portInput = SpinBox(self)
        self.portInput.setRange(1, 65535)
        self.portInput.setValue(22)
        self.pemPathInput = LineEdit(self)
        self.remarksInput = TextEdit(self)
        self.remarksInput.setFixedHeight(120)  # Made larger
        self.colorComboBox = ComboBox(self)

        # Setup Colors (Same as Bookmarks plugin)
        colors = [
            ("Default", None),
            ("Blue", "#0078d4"),
            ("Green", "#107c10"),
            ("Red", "#d13438"),
            ("Purple", "#5c2d91"),
            ("Orange", "#d83b01"),
        ]
        for name, hex_val in colors:
            self.colorComboBox.addItem(name, userData=hex_val)

        # Keys Dropdown Button
        self.keysBtn = TransparentToolButton(FluentIcon.HISTORY, self)
        self.keysBtn.setToolTip("Select from existing keys")
        self.keysBtn.clicked.connect(self._show_keys_menu)

        # Pem Browse Button
        self.browseBtn = PushButton("Browse", self)
        self.browseBtn.clicked.connect(self._on_browse_pem)

        pem_layout = QHBoxLayout()
        pem_layout.addWidget(self.pemPathInput)
        pem_layout.addWidget(self.keysBtn)
        pem_layout.addWidget(self.browseBtn)

        # Set Placeholders
        self.nameInput.setPlaceholderText("Connection Name (e.g. Production)")
        self.hostInput.setPlaceholderText("IP or Hostname")
        self.userInput.setPlaceholderText("Username (default: root)")
        self.pemPathInput.setPlaceholderText("Path to .pem file (optional)")
        self.remarksInput.setPlaceholderText("Remarks...")

        # Fill data if editing
        if data:
            self.nameInput.setText(data.get("name", ""))
            self.hostInput.setText(data.get("host", ""))
            self.userInput.setText(data.get("user", "root"))
            self.portInput.setValue(data.get("port", 22))
            self.pemPathInput.setText(data.get("pem_path", ""))
            self.remarksInput.setMarkdown(data.get("remarks", ""))

            color = data.get("color")
            if color:
                for i in range(self.colorComboBox.count()):
                    if self.colorComboBox.itemData(i) == color:
                        self.colorComboBox.setCurrentIndex(i)
                        break

        # Layout
        self.viewLayout.addWidget(self.titleLabel)
        form = QFormLayout()
        form.addRow("Name:", self.nameInput)
        form.addRow("Host:", self.hostInput)
        form.addRow("User:", self.userInput)
        form.addRow("Port:", self.portInput)
        form.addRow("PEM Path:", pem_layout)
        form.addRow("Color:", self.colorComboBox)
        form.addRow("Remarks:", self.remarksInput)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(450)

    def _show_keys_menu(self):
        """Show a menu with files in the keys directory."""
        if not self._keys_dir.exists():
            return

        files = list(self._keys_dir.glob("*"))
        if not files:
            InfoBar.info(
                "Info",
                "No keys found in local storage",
                duration=2000,
                parent=self.window(),
            )
            return

        menu = RoundMenu(parent=self)
        for f in files:
            if f.is_file():
                # Use a specific icon for keys if possible, or just COMMAND_PROMPT
                action = Action(FluentIcon.CERTIFICATE, f.name, self)
                action.triggered.connect(
                    lambda checked=False, name=f.name: self.pemPathInput.setText(name)
                )
                menu.addAction(action)

        # Position menu below the button
        menu.exec(self.keysBtn.mapToGlobal(self.keysBtn.rect().bottomLeft()))

    def _on_browse_pem(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PEM File", "", "PrivateKey Files (*.pem *.ppk);;All Files (*)"
        )
        if file_path:
            # Copy to local keys directory
            src = Path(file_path)
            dest = self._keys_dir / src.name

            try:
                if src.absolute() != dest.absolute():
                    shutil.copy2(src, dest)
                self.pemPathInput.setText(dest.name)
                InfoBar.success(
                    "Backup",
                    f"Key backed up to {dest.name}",
                    duration=2000,
                    parent=self.window(),
                )
            except Exception as e:
                InfoBar.error(
                    "Backup Failed", str(e), duration=3000, parent=self.window()
                )
                self.pemPathInput.setText(file_path)

    def get_data(self):
        return {
            "name": self.nameInput.text().strip(),
            "host": self.hostInput.text().strip(),
            "user": self.userInput.text().strip() or "root",
            "port": self.portInput.value(),
            "pem_path": self.pemPathInput.text().strip(),
            "remarks": self.remarksInput.toPlainText().strip(),
            "color": self.colorComboBox.currentData(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["name"] and data["host"])


class SSHManagerWidget(QWidget):
    """Main view for SSH Manager plugin."""

    connect_requested = Signal(int)

    def __init__(self, db, keys_dir, parent=None):
        super().__init__(parent)
        self.db = db
        self.keys_dir = keys_dir
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 20, 20, 20)
        self.mainLayout.setSpacing(15)

        # Header
        header = QHBoxLayout()
        self.titleLabel = BodyLabel("SSH Manager", self)
        self.titleLabel.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.addBtn = PushButton(FluentIcon.ADD, "Add Connection", self)
        self.addBtn.clicked.connect(self._on_add_clicked)

        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.addBtn)
        self.mainLayout.addLayout(header)

        # Scroll Area for Flow Layout
        self.scrollArea = BScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.flowLayout = FlowLayout(self.container)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setSpacing(15)

        self.scrollArea.setWidget(self.container)
        self.mainLayout.addWidget(self.scrollArea)

        self._refresh_list()

    def _refresh_list(self):
        """Reload connections from DB and update UI."""
        self.flowLayout.takeAllWidgets()

        conns = self.db.fetchall(
            "SELECT * FROM ssh_connections ORDER BY created_at DESC"
        )

        for conn in conns:
            # Use name-based access which is much safer across migrations
            c_id = conn["id"]
            name = conn["name"]
            host = conn["host"]
            user = conn["user"]
            port = conn["port"]
            remarks = conn["remarks"]

            # Safely handle color which might be missing in very old Row or if migration had issues
            try:
                color = conn["color"]
            except (IndexError, KeyError):
                color = None

            tile = SSHConnectionTile(
                c_id, name, host, user, port, remarks, color, self.container
            )
            tile.connect_requested.connect(self.connect_requested.emit)
            tile.scp_requested.connect(self._on_scp_clicked)
            tile.edit_requested.connect(self._on_edit_clicked)
            tile.delete_requested.connect(self._on_delete_clicked)
            self.flowLayout.addWidget(tile)

    def _on_add_clicked(self):
        dialog = SSHConnectionDialog(self.window(), keys_dir=self.keys_dir)
        if dialog.exec():
            data = dialog.get_data()
            if dialog.validate():
                self.db.execute(
                    """
                    INSERT INTO ssh_connections (name, host, user, port, pem_path, remarks, color)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["name"],
                        data["host"],
                        data["user"],
                        data["port"],
                        data["pem_path"],
                        data["remarks"],
                        data["color"],
                    ),
                )
                self._refresh_list()
                InfoBar.success(
                    "Success", "Connection added", duration=2000, parent=self.window()
                )
            else:
                InfoBar.error(
                    "Error",
                    "Name and Host are required",
                    duration=2000,
                    parent=self.window(),
                )

    def _on_scp_clicked(self, conn_id):
        conn = self.db.fetchone(
            "SELECT * FROM ssh_connections WHERE id = ?", (conn_id,)
        )
        if not conn:
            return

        connection = dict(conn)
        dialog = SFTPBrowserDialog(
            self.window(), connection=connection, keys_dir=self.keys_dir
        )
        dialog.exec()

    def _on_edit_clicked(self, conn_id):
        conn = self.db.fetchone(
            "SELECT * FROM ssh_connections WHERE id = ?", (conn_id,)
        )
        if not conn:
            return

        if isinstance(conn, dict):
            data = dict(conn)  # Ensure it's a mutable dict for safety
        else:
            # Based on updated schema: id=0, name=1, host=2, user=3, port=4, pem=5, remarks=6, color=7
            data = {
                "name": conn[1],
                "host": conn[2],
                "user": conn[3],
                "port": conn[4],
                "pem_path": conn[5],
                "remarks": conn[6],
                "color": conn[7] if len(conn) > 7 else None,
            }

        dialog = SSHConnectionDialog(self.window(), data=data, keys_dir=self.keys_dir)
        if dialog.exec():
            new_data = dialog.get_data()
            if dialog.validate():
                self.db.execute(
                    """
                    UPDATE ssh_connections 
                    SET name=?, host=?, user=?, port=?, pem_path=?, remarks=?, color=?
                    WHERE id=?
                    """,
                    (
                        new_data["name"],
                        new_data["host"],
                        new_data["user"],
                        new_data["port"],
                        new_data["pem_path"],
                        new_data["remarks"],
                        new_data["color"],
                        conn_id,
                    ),
                )
                self._refresh_list()
                InfoBar.success(
                    "Success", "Connection updated", duration=2000, parent=self.window()
                )

    def _on_delete_clicked(self, conn_id):
        # Could add a confirmation dialog here
        self.db.execute("DELETE FROM ssh_connections WHERE id = ?", (conn_id,))
        self._refresh_list()
        InfoBar.success(
            "Success", "Connection deleted", duration=2000, parent=self.window()
        )
