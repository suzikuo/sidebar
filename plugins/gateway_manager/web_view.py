from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from core.logger import logger
from core.web_ui import create_web_plugin_view


class GatewayInterface(QWidget):
    """Web-only Gateway page with an explicit local-load error state."""

    def __init__(self, registry, content_root, parent=None):
        super().__init__(parent)
        self._content_root = Path(content_root)
        self._web_view = None
        self._error_label = None
        self._disposed = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._load_web_view(registry)

    @property
    def using_web_view(self):
        return self._web_view is not None

    def _load_web_view(self, registry):
        if not (self._content_root / "index.html").is_file():
            self._show_error("Gateway web build is not available.")
            return
        try:
            self._web_view = create_web_plugin_view(
                registry,
                "gateway_manager",
                self._content_root,
                autoload=False,
                parent=self,
            )
            self._web_view.load_failed.connect(self._show_error)
            self._layout.addWidget(self._web_view)
            self._web_view.load()
        except Exception as exc:
            logger.error("Failed to initialize gateway web view", exc_info=True)
            self._show_error(str(exc))

    @Slot(str)
    def _show_error(self, reason):
        if self._disposed:
            return
        logger.error("Gateway web interface is unavailable: %s", reason)
        self._dispose_web_view()
        if self._error_label is None:
            self._error_label = QLabel(self)
            self._error_label.setObjectName("gateway_web_load_error")
            self._error_label.setAlignment(Qt.AlignCenter)
            self._error_label.setWordWrap(True)
            self._error_label.setStyleSheet(
                "padding: 24px; color: #E2E6EA; background: #202329;"
            )
            self._layout.addWidget(self._error_label)
        self._error_label.setText(
            "Gateway web interface could not be loaded.\n"
            "Check the bundled Gateway web assets and application log."
        )

    def _dispose_web_view(self):
        if self._web_view is None:
            return
        web_view = self._web_view
        self._web_view = None
        self._layout.removeWidget(web_view)
        web_view.dispose()
        web_view.deleteLater()

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self._dispose_web_view()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
