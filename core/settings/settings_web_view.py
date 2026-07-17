from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QStackedLayout, QWidget

from core.logger import logger
from core.web_ui import WebPluginHost

from .settings_api import SettingsApiService


class SettingsWebView(WebPluginHost):
    def __init__(
        self,
        registry,
        settings_manager,
        content_root,
        *,
        autoload=True,
        parent=None,
    ):
        super().__init__(
            registry,
            "settings",
            content_root,
            capabilities={
                SettingsApiService.READ_CAPABILITY,
                SettingsApiService.WRITE_CAPABILITY,
            },
            autoload=autoload,
            parent=parent,
        )
        self.setObjectName("settings_web_view")
        self._settings_manager = settings_manager
        self._settings_manager.settings_changed.connect(self._on_settings_changed)

    @Slot(str, str, object)
    def _on_settings_changed(self, category, key, value):
        self.bridge.publish_event(
            "settings.changed",
            {"category": category, "key": key, "value": value},
        )


class SettingsInterface(QWidget):
    """Web-first settings surface with a lazy native fallback."""

    def __init__(self, registry, settings_manager, content_root, parent=None):
        super().__init__(parent)
        self._registry = registry
        self._settings_manager = settings_manager
        self._content_root = Path(content_root)
        self._web_view = None
        self._native_view = None

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
            self._web_view = SettingsWebView(
                self._registry,
                self._settings_manager,
                self._content_root,
                autoload=False,
                parent=self,
            )
            self._web_view.load_failed.connect(self._show_native)
            self._layout.addWidget(self._web_view)
            self._layout.setCurrentWidget(self._web_view)
            self._web_view.load()
        except Exception as exc:
            logger.error("Failed to initialize web settings view", exc_info=True)
            self._show_native(str(exc))

    @Slot(str)
    def _show_native(self, reason):
        logger.warning("Using native settings fallback: %s", reason)
        if self._native_view is None:
            self._native_view = self._settings_manager.get_settings_widget()
            self._layout.addWidget(self._native_view)
        self._layout.setCurrentWidget(self._native_view)

        if self._web_view is not None:
            web_view = self._web_view
            self._web_view = None
            self._layout.removeWidget(web_view)
            web_view.close()
            web_view.deleteLater()
