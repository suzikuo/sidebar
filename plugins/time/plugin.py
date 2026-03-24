from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget
from qfluentwidgets import FluentIcon

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from plugins.time.logic import AlarmManager
from plugins.time.views import ClockWidget, TimeSettingsWidget
from plugins.time.desktop_clock import DesktopClockWidget


class TimePlugin(PluginBase):
    """
    Time Plugin: Refactored from built-in Sidebar clock.
    """

    def __init__(self, context):
        super().__init__(context)
        self._clock_widget = None
        self._settings_widget = None
        self._alarm_manager = None
        self._desktop_clock = None

    def on_load(self):
        logger.info("Time plugin loaded.")
        # Initialize Alarm Manager
        self._alarm_manager = AlarmManager(self.context)

        config = self.context.state.get(
            "config", {"enabled": True, "format": "HH:mm", "color": "white"}
        )

        if not self._desktop_clock:
            self._desktop_clock = DesktopClockWidget()
            self._desktop_clock.set_alarm_manager(self._alarm_manager)
            self._desktop_clock.position_changed.connect(self._on_desktop_clock_moved)

        self._desktop_clock.apply_config(config)

        if config.get("show_desktop", False):
            self._desktop_clock.show()
        else:
            self._desktop_clock.hide()

    def on_unload(self):
        logger.info("Time plugin unloaded.")
        self._alarm_manager = None
        self._settings_widget = None
        if self._desktop_clock:
            self._desktop_clock.close()
            self._desktop_clock = None

    def get_thumbnail_widget(self) -> QWidget:
        # We can just return a simple label or icon
        label = QLabel("⏱️")
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("font-size: 20px; color: white; background: transparent;")
        return label

    def get_card_widget(self) -> QWidget:
        """Returns the settings widget for the detail window."""
        if not self._settings_widget:
            self._settings_widget = TimeSettingsWidget(self._alarm_manager)
            # Load current config - Fix state access
            config = self.context.state.get(
                "config", {"enabled": True, "format": "HH:mm", "color": "white"}
            )
            self._settings_widget.set_config(config)
            self._settings_widget.config_changed.connect(self._on_config_changed)
        return self._settings_widget

    def get_sidebar_widget(self) -> QWidget | None:
        """Returns the clock widget for the sidebar."""
        # Fix state access
        config = self.context.state.get(
            "config", {"enabled": True, "format": "HH:mm", "color": "white"}
        )

        if not config.get("enabled", True):
            return None

        if not self._clock_widget:
            self._clock_widget = ClockWidget()
            self._clock_widget.set_config(config.get("format"), config.get("color"))
            if self._alarm_manager:
                self._clock_widget.set_alarm_manager(self._alarm_manager)

            # Connect click to open detail view
            self._clock_widget.clicked.connect(lambda: self.context.open_detail_view())

        return self._clock_widget

    def get_sidebar_widget_config(self) -> dict:
        """Size constraints for the clock."""
        return {"max_height": 120, "max_width": 100, "min_width": 40}

    def get_icon(self):
        return FluentIcon.DATE_TIME

    def _on_desktop_clock_moved(self, x: int, y: int):
        config = self.context.state.get("config", {})
        config["desktop_x"] = x
        config["desktop_y"] = y
        self.context.state.set("config", config)

    def _on_config_changed(self, config: dict):
        # Preserve window position (which is not in config UI)
        old_config = self.context.state.get("config", {})
        if "desktop_x" in old_config:
            config["desktop_x"] = old_config["desktop_x"]
        if "desktop_y" in old_config:
            config["desktop_y"] = old_config["desktop_y"]

        # Save to plugin state - Fix state access
        self.context.state.set("config", config)

        # Update clock if it exists
        if self._clock_widget:
            self._clock_widget.set_config(config.get("format"), config.get("color"))
            self._clock_widget.setVisible(config.get("enabled", True))
            
        if self._desktop_clock:
            self._desktop_clock.apply_config(config)
            if config.get("show_desktop", False):
                self._desktop_clock.show()
            else:
                self._desktop_clock.hide()

        # Note: If 'enabled' changed from False to True, main application
        # might need to re-add the widget. Since sidebar_widget is loaded
        # on plugin load, a simple visible toggle is better.
        # However, SidebarWindow.add_sidebar_widget only calls get_sidebar_widget() once.
        # For simplicity, we just toggle visibility.
