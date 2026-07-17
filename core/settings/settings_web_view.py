from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QStackedLayout, QWidget

from core.logger import logger
from core.web_ui import create_web_plugin_view

from .settings_api import SettingsApiService


class SettingsInterface(QWidget):
    """Web-first settings surface with a lazy native fallback."""

    def __init__(self, registry, settings_manager, content_root, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._settings_manager = settings_manager
        self._content_root = Path(content_root)
        self._web_view = None
        self._native_view = None
        self._disposed = False

        self._layout = QStackedLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._load_web_view()

    @property
    def using_web_view(self):
        return self._web_view is not None and self._layout.currentWidget() is self._web_view

    def _load_web_view(self):
        if not (self._content_root / "index.html").is_file():
            self._show_native("Web settings build is not available.")
            return

        try:
            self._web_view = create_web_plugin_view(
                self._registry,
                "settings",
                self._content_root,
                capabilities={
                    SettingsApiService.READ_CAPABILITY,
                    SettingsApiService.WRITE_CAPABILITY,
                },
                autoload=False,
                parent=self,
            )
            self._web_view.setObjectName("settings_web_view")
            self._settings_manager.settings_changed.connect(self._on_settings_changed)
            self._web_view.load_failed.connect(self._show_native)
            self._layout.addWidget(self._web_view)
            self._layout.setCurrentWidget(self._web_view)
            self._web_view.load()
        except Exception as exc:
            logger.error("Failed to initialize web settings view", exc_info=True)
            self._show_native(str(exc))

    @Slot(str)
    def _show_native(self, reason):
        if self._disposed:
            return
        logger.warning("Using native settings fallback: %s", reason)
        if self._native_view is None:
            self._native_view = self._settings_manager.get_settings_widget()
            self._layout.addWidget(self._native_view)
        self._layout.setCurrentWidget(self._native_view)

        if self._web_view is not None:
            web_view = self._web_view
            self._web_view = None
            self._layout.removeWidget(web_view)
            web_view.dispose()
            web_view.deleteLater()

    @Slot(str, str, object)
    def _on_settings_changed(self, category, key, value):
        if self._web_view:
            self._web_view.bridge.publish_event(
                "settings.changed",
                {"category": category, "key": key, "value": value},
            )

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        try:
            self._settings_manager.settings_changed.disconnect(self._on_settings_changed)
        except (AttributeError, RuntimeError):
            pass
        if self._web_view:
            web_view = self._web_view
            self._web_view = None
            self._layout.removeWidget(web_view)
            web_view.dispose()
            web_view.deleteLater()

    def closeEvent(self, event):
        self.dispose()
        super().closeEvent(event)
