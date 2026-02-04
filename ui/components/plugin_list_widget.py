"""
Plugin List Widget - Displays plugin information with enable/disable controls
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel

from ui.components.base_widget import BScrollArea


class PluginItemWidget(QFrame):
    """Individual plugin item in the list."""

    toggled = Signal(str, bool)  # plugin_id, enabled
    reload_requested = Signal(str)  # plugin_id

    def __init__(self, plugin_id: str, manifest: dict, enabled: bool = True):
        super().__init__()
        self.plugin_id = plugin_id
        self.manifest = manifest

        self.setObjectName("PluginItem")
        self.setStyleSheet("""
            #PluginItem {
                background-color: #FFF;
                border-radius: 8px;
                border: 1px solid #EEE;
                padding: 12px;
            }
            #PluginItem:hover {
                border-color: #DDD;
                background-color: #FAFAFA;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Left: Plugin info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)

        # Plugin name
        name_label = BodyLabel(manifest.get("name", plugin_id))
        name_font = QFont()
        name_font.setPointSize(14)
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet("color: #333;")
        info_layout.addWidget(name_label)

        # Plugin version and ID
        version_text = f"v{manifest.get('version', '1.0.0')} • {plugin_id}"
        version_label = BodyLabel(version_text)
        version_label.setStyleSheet("color: #888; font-size: 11px;")
        info_layout.addWidget(version_label)

        # Plugin description
        if "description" in manifest:
            desc_label = BodyLabel(manifest["description"])
            desc_label.setStyleSheet("color: #666; font-size: 12px;")
            desc_label.setWordWrap(True)
            info_layout.addWidget(desc_label)

        layout.addLayout(info_layout, 1)

        # Right: Controls
        controls_layout = QVBoxLayout()
        controls_layout.setAlignment(Qt.AlignTop | Qt.AlignRight)
        controls_layout.setSpacing(8)

        # Enable/Disable toggle
        self.enable_checkbox = QCheckBox("Enabled")
        self.enable_checkbox.setChecked(enabled)
        self.enable_checkbox.toggled.connect(self._on_toggled)
        self.enable_checkbox.setStyleSheet("""
            QCheckBox {
                font-size: 12px;
                color: #555;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
        """)
        controls_layout.addWidget(self.enable_checkbox)

        # Reload button
        reload_btn = QPushButton("Reload")
        reload_btn.setFixedWidth(80)
        reload_btn.clicked.connect(lambda: self.reload_requested.emit(self.plugin_id))
        reload_btn.setStyleSheet("""
            QPushButton {
                background-color: #F5F5F5;
                border: 1px solid #DDD;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                color: #555;
            }
            QPushButton:hover {
                background-color: #E8E8E8;
                border-color: #CCC;
            }
            QPushButton:pressed {
                background-color: #DDD;
            }
        """)
        controls_layout.addWidget(reload_btn)

        layout.addLayout(controls_layout)

    def _on_toggled(self, checked: bool):
        """Emit signal when toggle state changes."""
        self.toggled.emit(self.plugin_id, checked)


class PluginListWidget(QWidget):
    """Scrollable list of all plugins."""

    plugin_toggled = Signal(str, bool)
    plugin_reload_requested = Signal(str)

    def __init__(self, plugin_manager, settings_manager):
        super().__init__()
        self.plugin_manager = plugin_manager
        self.settings_manager = settings_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Header
        header_layout = QHBoxLayout()
        header_label = BodyLabel("Installed Plugins")
        header_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #333;")
        header_layout.addWidget(header_label)

        header_layout.addStretch()

        # Refresh button
        refresh_btn = QPushButton("Refresh All")
        refresh_btn.clicked.connect(self._refresh_plugins)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF6B9D;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #FF5A8C;
            }
        """)
        header_layout.addWidget(refresh_btn)

        layout.addLayout(header_layout)

        # Scroll area for plugins
        scroll = BScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)

        self.plugins_container = QWidget()
        self.plugins_layout = QVBoxLayout(self.plugins_container)
        self.plugins_layout.setSpacing(10)
        self.plugins_layout.setAlignment(Qt.AlignTop)

        scroll.setWidget(self.plugins_container)
        layout.addWidget(scroll)

        # Load plugins
        self._load_plugins()

    def _load_plugins(self):
        """Load and display all plugins."""
        # Clear existing
        while self.plugins_layout.count():
            item = self.plugins_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Get enabled plugins from settings
        enabled_plugins = self.settings_manager.get_setting("plugins", "enabled", [])
        disabled_plugins = self.settings_manager.get_setting("plugins", "disabled", [])

        # Add plugin items
        if hasattr(self.plugin_manager, "_manifests"):
            for plugin_id, manifest in self.plugin_manager._manifests.items():
                # Determine if enabled (default to True if not in either list)
                is_enabled = plugin_id not in disabled_plugins

                item = PluginItemWidget(plugin_id, manifest, is_enabled)
                item.toggled.connect(self._on_plugin_toggled)
                item.reload_requested.connect(self._on_plugin_reload)
                self.plugins_layout.addWidget(item)

        if self.plugins_layout.count() == 0:
            no_plugins = BodyLabel("No plugins installed")
            no_plugins.setStyleSheet("color: #999; font-style: italic; padding: 20px;")
            no_plugins.setAlignment(Qt.AlignCenter)
            self.plugins_layout.addWidget(no_plugins)

    def _on_plugin_toggled(self, plugin_id: str, enabled: bool):
        """Handle plugin enable/disable."""
        enabled_list = self.settings_manager.get_setting("plugins", "enabled", [])
        disabled_list = self.settings_manager.get_setting("plugins", "disabled", [])

        if enabled:
            # Enable plugin
            if plugin_id in disabled_list:
                disabled_list.remove(plugin_id)
            if plugin_id not in enabled_list:
                enabled_list.append(plugin_id)
        else:
            # Disable plugin
            if plugin_id in enabled_list:
                enabled_list.remove(plugin_id)
            if plugin_id not in disabled_list:
                disabled_list.append(plugin_id)

        self.settings_manager.set_setting("plugins", "enabled", enabled_list)
        self.settings_manager.set_setting("plugins", "disabled", disabled_list)

        self.plugin_toggled.emit(plugin_id, enabled)

    def _on_plugin_reload(self, plugin_id: str):
        """Handle plugin reload request."""
        self.plugin_reload_requested.emit(plugin_id)

    def _refresh_plugins(self):
        """Refresh the plugin list."""
        self._load_plugins()
