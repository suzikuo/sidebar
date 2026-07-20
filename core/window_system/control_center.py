"""Standalone control center window hosting the local Vue application."""

from pathlib import Path

from PySide6.QtCore import QPoint, Qt, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from core.control_center.api import ControlCenterApiService
from core.logger import logger
from core.settings import SettingsApiService
from core.web_ui import create_web_plugin_view


class ControlCenterWindow(QMainWindow):
    STATE_KEY = "control_center_window"

    def __init__(self, registry, state_store, content_root, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._state_store = state_store
        self._content_root = Path(content_root)
        self._web_host = None
        self._disposed = False

        self.setObjectName("ControlCenterWindow")
        self.setWindowTitle("Agile Tiles 控制中心")
        self.setMinimumSize(820, 600)
        self.resize(1080, 760)

        central = QWidget(self)
        self._stack = QStackedLayout(central)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(central)

        self._error_view = self._create_error_view()
        self._stack.addWidget(self._error_view)
        self._restore_geometry()
        self._load_web_view()

    def publish_event(self, event_name, payload=None):
        if self._web_host is not None:
            self._web_host.bridge.publish_event(event_name, payload or {})

    def show_center(self):
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._save_geometry()
        self._dispose_web_host()

    def force_close(self):
        self.dispose()
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.close()

    def closeEvent(self, event):
        if self._disposed:
            event.accept()
            return
        self._save_geometry()
        event.ignore()
        self.hide()

    @Slot()
    def _load_web_view(self):
        if self._disposed:
            return
        self._dispose_web_host()
        entry = self._content_root / "index.html"
        if not entry.is_file():
            self._show_error("控制中心前端资源不存在，请重新构建或安装应用。")
            return
        try:
            self._web_host = create_web_plugin_view(
                self._registry,
                "control-center",
                self._content_root,
                capabilities={
                    SettingsApiService.READ_CAPABILITY,
                    SettingsApiService.WRITE_CAPABILITY,
                    ControlCenterApiService.READ_CAPABILITY,
                    ControlCenterApiService.MANAGE_CAPABILITY,
                },
                autoload=False,
                parent=self,
            )
            self._web_host.setObjectName("control_center_web_host")
            self._web_host.load_failed.connect(self._show_error)
            self._stack.addWidget(self._web_host)
            self._stack.setCurrentWidget(self._web_host)
            self._web_host.load()
        except Exception as error:
            logger.error("Failed to create control center web host", exc_info=True)
            self._show_error(str(error))

    @Slot(str)
    def _show_error(self, message):
        self._error_label.setText(message)
        self._stack.setCurrentWidget(self._error_view)
        self._dispose_web_host()

    def _create_error_view(self):
        widget = QWidget(self)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch(1)
        title = QLabel("控制中心无法加载", widget)
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        layout.addWidget(title)
        self._error_label = QLabel("", widget)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #8a8f98; margin: 12px 0;")
        layout.addWidget(self._error_label)
        retry = QPushButton("重试", widget)
        retry.setFixedWidth(96)
        retry.clicked.connect(self._load_web_view)
        layout.addWidget(retry)
        layout.addStretch(2)
        return widget

    def _dispose_web_host(self):
        if self._web_host is None:
            return
        host = self._web_host
        self._web_host = None
        self._stack.removeWidget(host)
        host.dispose()
        host.deleteLater()

    def _restore_geometry(self):
        state = self._state_store.get_system_state(self.STATE_KEY, {})
        if not isinstance(state, dict):
            state = {}
        width = max(
            self.minimumWidth(), self._state_int(state, "width", self.width())
        )
        height = max(
            self.minimumHeight(), self._state_int(state, "height", self.height())
        )
        self.resize(width, height)
        if "x" in state and "y" in state:
            position = QPoint(
                self._state_int(state, "x", self.x()),
                self._state_int(state, "y", self.y()),
            )
            if QGuiApplication.screenAt(position):
                self.move(position)
                return
        screen = QGuiApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.move(
                available.center().x() - self.width() // 2,
                available.center().y() - self.height() // 2,
            )

    @staticmethod
    def _state_int(state, key, default):
        try:
            return int(state.get(key, default))
        except (TypeError, ValueError):
            return int(default)

    def _save_geometry(self):
        geometry = self.normalGeometry()
        self._state_store.set_system_state(
            self.STATE_KEY,
            {
                "x": geometry.x(),
                "y": geometry.y(),
                "width": geometry.width(),
                "height": geometry.height(),
            },
        )
