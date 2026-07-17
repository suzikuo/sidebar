from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QStackedLayout, QWidget

from core.logger import logger
from core.web_ui import create_web_plugin_view


class GatewayInterface(QWidget):
    """Web-first gateway page with the existing native view as a lazy fallback."""

    def __init__(self, registry, content_root, native_factory, parent=None):
        super().__init__(parent)
        self._content_root = Path(content_root)
        self._native_factory = native_factory
        self._web_view = None
        self._native_view = None
        self._disposed = False

        self._layout = QStackedLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._load_web_view(registry)

    @property
    def using_web_view(self):
        return self._web_view is not None and self._layout.currentWidget() is self._web_view

    def _load_web_view(self, registry):
        if not (self._content_root / "index.html").is_file():
            self._show_native("Gateway web build is not available.")
            return
        try:
            self._web_view = create_web_plugin_view(
                registry,
                "gateway_manager",
                self._content_root,
                autoload=False,
                parent=self,
            )
            self._web_view.load_failed.connect(self._show_native)
            self._layout.addWidget(self._web_view)
            self._layout.setCurrentWidget(self._web_view)
            self._web_view.load()
        except Exception as exc:
            logger.error("Failed to initialize gateway web view", exc_info=True)
            self._show_native(str(exc))

    @Slot(str)
    def _show_native(self, reason):
        if self._disposed:
            return
        logger.warning("Using native gateway fallback: %s", reason)
        if self._native_view is None:
            self._native_view = self._native_factory()
            self._layout.addWidget(self._native_view)
        self._layout.setCurrentWidget(self._native_view)
        self._dispose_web_view()

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
