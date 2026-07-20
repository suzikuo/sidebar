"""
Settings Manager - Core system component for managing application settings.
This is NOT a plugin, but a built-in system feature.
"""

import copy

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .settings_schema import get_setting_defaults


class SettingsManager(QObject):
    """
    Manages application settings as a core system component.
    Provides the settings UI and handles settings persistence.
    """

    settings_changed = Signal(str, str, object)  # category, key, value

    DEFAULTS = get_setting_defaults()

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

        # The former general toggle remains authoritative for installations that
        # predate the dedicated notifications category.
        if "notifications" not in stored_settings:
            self.settings["notifications"]["enabled"] = stored_settings.get(
                "general", {}
            ).get("enable_notifications", True)

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

    def set_settings_batch(self, changes):
        """Persist a validated group of settings with one state-store write."""
        for category, key, value in changes:
            if category not in self.settings:
                self.settings[category] = {}
            self.settings[category][key] = copy.deepcopy(value)
        self._save_settings()
        for category, key, value in changes:
            self.settings_changed.emit(category, key, value)

    def get_all_settings(self):
        """Get all settings as a dictionary."""
        return copy.deepcopy(self.settings)

    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        previous = self.get_all_settings()
        self.settings = copy.deepcopy(self.DEFAULTS)
        self._save_settings()
        self._emit_setting_differences(previous, self.settings)

    def reset_category(self, category):
        if category not in self.DEFAULTS:
            raise KeyError(category)
        previous = copy.deepcopy(self.settings.get(category, {}))
        self.settings[category] = copy.deepcopy(self.DEFAULTS[category])
        self._save_settings()
        self._emit_setting_differences(
            {category: previous},
            {category: self.settings[category]},
        )

    def _emit_setting_differences(self, before, after):
        for category, values in after.items():
            previous = before.get(category, {})
            for key, value in values.items():
                if previous.get(key) != value:
                    self.settings_changed.emit(category, key, value)

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
