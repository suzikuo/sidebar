"""
Settings Manager - Core system component for managing application settings.
This is NOT a plugin, but a built-in system feature.
"""

import copy

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class SettingsManager(QObject):
    """
    Manages application settings as a core system component.
    Provides the settings UI and handles settings persistence.
    """

    settings_changed = Signal(str, str, object)  # category, key, value

    # Default settings
    DEFAULTS = {
        "general": {
            "run_on_startup": False,
            "enable_notifications": True,
            "auto_hide_delay": 1000,  # milliseconds
            "trigger_zone_width": 5,  # pixels
        },
        "appearance": {
            "theme_mode": "dark",  # 'light', 'dark', 'system'
            "sidebar_position": "right",  # 'left', 'right'
            "sidebar_width": 500,
            "collapsed_width": 48,
            "icon_size": 40,
            "font_family": "Segoe UI",
            "font_size": 13,
            "font_weight": "normal",  # 'light', 'normal', 'medium', 'bold'
            "accent_color": "#FF6B9D",
            "peek_width": 2,  # 1 to 10 pixels
            "sidebar_bg_opacity": 0.9,  # 0.1 to 1.0
            "detail_bg_opacity": 0.9,  # 0.1 to 1.0
            "sidebar_height_percent": 0.8,  # 0.2 to 1.0
            "sidebar_hidden_height_percent": 0.8,  # 0.2 to 1.0
            "sidebar_y_offset": 0,  # pixels from center
        },
        "plugins": {
            "enabled": [],  # List of enabled plugin IDs
            "disabled": [],  # List of disabled plugin IDs
        },
        "shortcuts": {
            "toggle_sidebar": "alt+space",
        },
    }

    def __init__(self, theme_engine, state_store):
        super().__init__()
        self.theme_engine = theme_engine
        self.state_store = state_store
        self.plugin_manager = None
        self._settings_card = None
        self._load_settings()

    def set_plugin_manager(self, plugin_manager):
        """Set the plugin manager reference."""
        self.plugin_manager = plugin_manager

    def _load_settings(self):
        """Load settings from state store or initialize with defaults."""
        stored_settings = self.state_store.get("settings", {})

        # Merge with defaults (defaults take precedence for missing keys)
        self.settings = {}
        for category, values in self.DEFAULTS.items():
            self.settings[category] = {**values, **stored_settings.get(category, {})}

        # Migrate old settings to new format
        self._migrate_settings()

    def _migrate_settings(self):
        """Migrate old settings to new format."""
        appearance = self.settings.get("appearance", {})

        # Migrate old sidebar_opacity to new separate settings
        if "sidebar_opacity" in appearance and "sidebar_bg_opacity" not in appearance:
            old_opacity = appearance["sidebar_opacity"]
            appearance["sidebar_bg_opacity"] = old_opacity
            appearance["detail_bg_opacity"] = old_opacity
            # Remove old setting
            del appearance["sidebar_opacity"]
            self._save_settings()

    def get_setting(self, category: str, key: str, default=None):
        """Get a specific setting value."""
        return self.settings.get(category, {}).get(key, default)

    def set_setting(self, category: str, key: str, value):
        """Set a specific setting value and persist it."""
        if category not in self.settings:
            self.settings[category] = {}

        self.settings[category][key] = value
        self._save_settings()
        self.settings_changed.emit(category, key, value)

    def get_all_settings(self):
        """Get all settings as a dictionary."""
        return copy.deepcopy(self.settings)

    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        self.settings = {}
        for category, values in self.DEFAULTS.items():
            self.settings[category] = values.copy()
        self._save_settings()

    def _save_settings(self):
        """Save settings to state store."""
        self.state_store.set("settings", self.settings)

    def get_thumbnail_widget(self):
        """Generate the settings icon for the sidebar."""

        class SettingsIcon(QWidget):
            def paintEvent(self, event):
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)

                # Draw Gear
                center_x, center_y = self.width() / 2, self.height() / 2
                size = min(self.width(), self.height()) * 0.4

                pen_color = QColor("white")

                painter.setPen(QPen(pen_color, 2))
                painter.setBrush(Qt.NoBrush)

                # Draw Circle
                painter.drawEllipse(
                    QPoint(int(center_x), int(center_y)), int(size), int(size)
                )
                # Draw Center Dot
                painter.setBrush(QBrush(pen_color))
                painter.drawEllipse(QPoint(int(center_x), int(center_y)), 3, 3)

        icon = SettingsIcon()
        icon.setObjectName("SettingsThumbnail")
        return icon

    def get_settings_widget(self):
        """Get the settings widget (using Fluent Design)."""
        return self.get_card_widget()

    def get_card_widget(self):
        """Get the settings card widget (using Fluent Design)."""
        if self._settings_card is None:
            try:
                from .fluent_settings_card import FluentSettingsCard

                self._settings_card = FluentSettingsCard(self)
            except ImportError:
                # Fallback to original if Fluent not available
                from .settings_card import SettingsCard

                self._settings_card = SettingsCard(self)

        return self._settings_card

    def get_preferred_width(self):
        """Settings needs more space for its two-column layout."""
        return self.get_setting("appearance", "sidebar_width", 500)
