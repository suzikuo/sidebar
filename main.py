#!/usr/bin/env python
"""
Agile Tiles - Main Entry Point
Following official qfluentwidgets demo pattern:
1. Create QApplication FIRST
2. Import all modules AFTER QApplication exists
3. Create window and run
"""

import os
import sys

from PySide6.QtCore import QObject, Slot  # noqa: E402
from PySide6.QtGui import QAction, QFont  # noqa: E402
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
)

# STEP 1: Create QApplication FIRST - BEFORE any other imports
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    NavigationItemPosition,
    PushButton,
    Theme,
    setTheme,
    setThemeColor,
)

from core.data_layer.data_service import DataService
from core.data_layer.path_utils import PathManager
from core.input_system.shortcut_manager import ShortcutManager
from core.logger import logger
from core.plugin_system.event_bus import EventBus
from core.plugin_system.plugin_manager import PluginManager
from core.settings.settings_manager import SettingsManager
from core.state_store import StateStore
from core.ui_kernel.design_tokens import DesignTokens
from core.ui_kernel.theme_engine import ThemeEngine
from core.window_system.main_window import DetailWindow
from core.window_system.sidebar import SidebarWindow

# Add project root to Python path for absolute imports
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
# Create QApplication at module level - this is the official pattern
app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)


class PluginErrorDialog(QDialog):
    """Standalone error dialog for plugin loading failures."""

    def __init__(self, errors: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Load Errors")
        self.setMinimumWidth(450)

        # Basic fluent-like styling for standalone dialog
        self.setStyleSheet(
            """
            QDialog {
                background-color: #202020;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
            }
            QLabel {
                color: white;
            }
        """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Title
        title = BodyLabel("Plugin Load Errors", self)
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #ff6b9d;")
        layout.addWidget(title)

        # Message
        msg = "The following plugins encountered errors during startup:\n"
        for pid, err in errors.items():
            msg += f"\n• {pid}:\n  {err}\n"

        content = BodyLabel(msg, self)
        content.setWordWrap(True)
        layout.addWidget(content)

        layout.addStretch(1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.ok_btn = PushButton("Understood", self)
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)
        layout.addLayout(btn_layout)

        # Center on screen
        self._center_on_screen()

    def _center_on_screen(self):
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)


class AppSignals(QObject):
    def __init__(self, app_instance):
        super().__init__()
        self.app = app_instance

    @Slot()
    def toggle_sidebar(self):
        self.app._do_toggle_sidebar()

    @Slot(str)
    def activate_plugin(self, plugin_id):
        self.app._do_activate_plugin(plugin_id)


class AgileTilesApp:
    def __init__(self):
        self.signals = AppSignals(self)
        self.app = app  # Use the global QApplication

        # 0. Set Fluent Theme
        setTheme(Theme.DARK)
        setThemeColor("#FF6B9D")  # Pink accent color

        # 0. Migrate Data and Get Paths
        PathManager.migrate_data()
        db_path = PathManager.get_config_path("app.db")
        state_path = PathManager.get_config_path("state.json")

        # 1. Initialize Core Services
        self.event_bus = EventBus()
        self.data_service = DataService(db_path)
        self.state_store = StateStore(state_path)
        self.tokens = DesignTokens()
        self.theme_engine = ThemeEngine(self.tokens)

        # 2. Initialize Core Settings (NOT a plugin)
        self.settings_manager = SettingsManager(self.theme_engine, self.state_store)

        # 2.1 Initialize Shortcut Manager
        self.shortcut_manager = ShortcutManager(self.settings_manager)

        # 3. Apply saved settings to theme engine
        self._apply_saved_settings()

        # 4. Setup UI - Dual Window Architecture
        # 4a. Create Sidebar Window (The primary interaction point)
        self.sidebar_window = SidebarWindow(self.state_store)

        # 4b. Create Detail Window (Background content holder)
        self.detail_window = DetailWindow(self.theme_engine, self.state_store)

        # 4c. Connect them
        # Enable coordinated hiding logic
        self.sidebar_window.set_detail_window(self.detail_window)

        # When sidebar item clicked -> Show corresponding content in Detail Window (Open Detail)
        self.sidebar_window.plugin_selected.connect(self._handle_plugin_selection)

        # When sidebar item left-clicked -> Perform quick action OR show detail
        self.sidebar_window.plugin_action_triggered.connect(self._handle_plugin_action)

        # When context menu is requested -> Populate it
        self.sidebar_window.populate_context_menu.connect(self._on_sidebar_context_menu)

        # 4d. Connect Settings Updates
        self.settings_manager.settings_changed.connect(self._on_settings_changed)

        # 5. Initialize Plugin System
        plugins_dirs = [str(p) for p in PathManager.get_plugin_search_paths()]
        self.plugin_manager = PluginManager(
            plugins_dirs, self.event_bus, self.state_store
        )
        self.plugin_manager.plugin_loaded.connect(self._on_plugin_loaded)
        self.plugin_manager.plugin_unloaded.connect(self._on_plugin_unloaded)
        self.plugin_manager.plugin_order_changed.connect(
            self.sidebar_window.update_plugin_order
        )

        self.settings_manager.set_plugin_manager(self.plugin_manager)

        # 6. Load Settings and Plugins
        self._setup_navigation()

        # 7. Setup Tray Icon
        self.setup_tray()

        # 8. Setup Global Notifications
        self.event_bus.subscribe("system:notification", self._on_system_notification)

        # 9. Setup Global Shortcuts
        self._setup_shortcuts()

        # 10. Setup Detail View Close Listener
        self.event_bus.subscribe(
            "system:close_detail", lambda _: self.detail_window.hide_content()
        )

    def _on_system_notification(self, data: dict):
        """Handle system notification events."""
        title = data.get("title", "Agile Tiles")
        message = data.get("message", "")
        # icon = data.get("icon", QSystemTrayIcon.Information) # Default icon
        # duration = data.get("duration", 3000)

        # Ensure tray icon is available
        if hasattr(self, "tray_icon") and self.tray_icon.isVisible():
            self.tray_icon.showMessage(
                title, message, QSystemTrayIcon.Information, 3000
            )

    def _setup_shortcuts(self):
        """Register global shortcuts."""
        # Toggle Sidebar (Expand/Collapse)
        self.shortcut_manager.register_shortcut(
            "toggle_sidebar", "alt+space", self._toggle_sidebar
        )

    def _toggle_sidebar(self):
        """Toggle sidebar expand/collapse (Thread-safe wrapper)."""
        # Ensure this runs on main thread if needed, but QWidget.show/hide are usually safe
        # Or trigger via signal if issues arise
        if self.sidebar_window.isVisible():
            # If visible but not active, maybe activate it?
            # Or just hide it. Let's implementing toggle logic.
            # But sidebar implies "Show" mostly.
            # If hidden, show. If shown, hide?
            # Usually global shortcut is for "Show / Bring to front"
            pass

        # We need a proper toggle.
        # Check if window is foreground.
        # For now, let's just make it show/hide based on current state.

        # Use QMetaObject.invokeMethod to ensure thread safety with GUI
        from PySide6.QtCore import QMetaObject, Qt

        QMetaObject.invokeMethod(self.signals, "toggle_sidebar", Qt.QueuedConnection)

    def _do_toggle_sidebar(self):
        """Actual toggle logic running in main thread."""
        self.sidebar_window.show()
        if self.sidebar_window.is_hidden:
            self.sidebar_window.expand()
            self.sidebar_window.activateWindow()
        else:
            self.sidebar_window.collapse()

    def _apply_saved_settings(self):
        """Apply saved settings to theme engine on startup."""
        # Apply theme mode
        theme_mode = self.settings_manager.get_setting(
            "appearance", "theme_mode", "dark"
        )
        self.theme_engine.set_theme_mode(theme_mode)

        # Apply qfluentwidgets theme
        if theme_mode == "light":
            setTheme(Theme.LIGHT)
        elif theme_mode == "dark":
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.AUTO)

        # Apply accent color
        accent_color = self.settings_manager.get_setting(
            "appearance", "accent_color", "#FF6B9D"
        )
        setThemeColor(accent_color)

        # Apply font settings globally using standard Qt mechanism
        font_family = self.settings_manager.get_setting(
            "appearance", "font_family", "Segoe UI"
        )
        font_size = self.settings_manager.get_setting("appearance", "font_size", 13)
        # Ensure font size is valid (must be > 0)
        if not isinstance(font_size, int) or font_size <= 0:
            font_size = 13
        self.theme_engine.set_font(font_family, font_size)

        # Create and apply global font
        font = QFont(font_family)

        font.setPointSize(font_size)
        self.app.setFont(font)

        # Apply accent color to theme engine
        self.theme_engine.set_accent_color(accent_color)

    def _on_plugin_loaded(self, plugin_id: str, instance):
        """Called when a plugin is loaded."""
        try:
            logger.info(f"Plugin loaded: {plugin_id}")

            # Get the plugin card widget
            widget = instance.get_card_widget()
            if widget:
                # Get plugin name from manifest or use id
                name = getattr(
                    instance, "name", plugin_id.split(".")[-1].replace("_", " ").title()
                )

                # Add to Sidebar (Icons)
                icon = getattr(instance, "get_icon", lambda: FluentIcon.APPLICATION)()
                description = getattr(instance, "description", "")
                tooltip = f"{name}\n{description}" if description else name
                self.sidebar_window.add_item(
                    route_key=plugin_id, icon=icon, text=name, tooltip=tooltip
                )

                # Add to Detail Window (Content)
                self.detail_window.add_plugin_interface(plugin_id, widget, name)

                # Add sidebar widget if provided (e.g. lyrics display)
                try:
                    sidebar_widget = instance.get_sidebar_widget()
                    if sidebar_widget is not None:
                        # Special case: Time plugin stays at the far end (stretch)
                        is_stretch = plugin_id == "time"

                        # Fetch configuration
                        config = {}
                        if hasattr(instance, "get_sidebar_widget_config"):
                            config = instance.get_sidebar_widget_config()

                        self.sidebar_window.add_sidebar_widget(
                            sidebar_widget, stretch=is_stretch, config=config
                        )
                except Exception as e:
                    logger.warning(f"Plugin {plugin_id} get_sidebar_widget error: {e}")

                # Register Plugin Shortcut (if any)
                # We use the plugin_id as key. Default None (user must set it)
                self.shortcut_manager.register_shortcut(
                    f"plugin.{plugin_id}",
                    None,
                    lambda pid=plugin_id: self._activate_plugin(pid),
                )
        except Exception as e:
            logger.error(
                f"UI initialization failed for plugin {plugin_id}: {e}", exc_info=True
            )
            self.plugin_manager.record_load_error(plugin_id, f"UI Error: {e}")

    def _activate_plugin(self, plugin_id):
        """Activate a specific plugin from shortcut."""
        from PySide6.QtCore import Q_ARG, QMetaObject, Qt

        QMetaObject.invokeMethod(
            self.signals, "activate_plugin", Qt.QueuedConnection, Q_ARG(str, plugin_id)
        )

    def _do_activate_plugin(self, plugin_id):
        """Actual activation logic."""
        self.show_window()
        self.sidebar_window.navigationInterface.setCurrentItem(plugin_id)
        # Open the specific plugin
        # We need to simulate a click or just call show_plugin
        # Also need sidebar geometry
        self.detail_window.show_plugin(plugin_id, self.sidebar_window.geometry_rect)

    def _on_plugin_unloaded(self, plugin_id: str):
        """Called when a plugin is unloaded."""
        logger.info(f"Plugin unloaded: {plugin_id}")
        self.sidebar_window.remove_item(plugin_id)
        self.detail_window.remove_plugin_interface(plugin_id)

    def _handle_plugin_selection(self, plugin_id: str):
        """Handle formal 'Selection' (e.g. from context menu)."""
        self.sidebar_window.navigationInterface.setCurrentItem(plugin_id)
        self.detail_window.show_plugin(plugin_id, self.sidebar_window.geometry_rect)

    def _handle_plugin_action(self, plugin_id: str):
        """Handle sidebar left-click on a plugin."""
        # 1. Special case for core settings
        if plugin_id == "settings":
            self.sidebar_window.navigationInterface.setCurrentItem(plugin_id)
            self.detail_window.show_plugin(plugin_id, self.sidebar_window.geometry_rect)
            return

        # 2. Find plugin instance
        instance = self.plugin_manager.get_plugin(plugin_id)
        if not instance:
            return

        # 3. Try to run quick action
        handled = False
        try:
            # Check if run() is overridden or exists
            if hasattr(instance, "run"):
                handled = instance.run()
        except Exception as e:
            logger.error(f"Error running plugin {plugin_id}: {e}", exc_info=True)

        # 4. If not handled, show the detail window
        if not handled:
            self.sidebar_window.navigationInterface.setCurrentItem(plugin_id)
            self.detail_window.show_plugin(plugin_id, self.sidebar_window.geometry_rect)

    def _on_sidebar_context_menu(self, plugin_id: str, menu):
        """Populate sidebar context menu with plugin-specific items."""
        # Special case for settings (currently no custom actions, but could add reset etc)
        if plugin_id == "settings":
            return

        # Find plugin instance
        instance = self.plugin_manager.get_plugin(plugin_id)
        if not instance:
            return

        try:
            # Get custom actions
            actions = instance.get_context_menu_items()
            if actions:
                menu.addSeparator()
                for action in actions:
                    if isinstance(action, QMenu):
                        menu.addMenu(action)
                    else:
                        menu.addAction(action)

        except Exception as e:
            logger.error(
                f"Error population context menu for {plugin_id}: {e}", exc_info=True
            )

    def _setup_navigation(self):
        """Setup the navigation with settings and plugins."""
        # Discover and load plugins
        self.plugin_manager.discover_and_load()

        # Add Settings (needs to be added to navigation explicitly)
        settings_widget = self.settings_manager.get_settings_widget()

        self.sidebar_window.add_item(
            route_key="settings",
            icon=FluentIcon.SETTING,
            text="Settings",
            position=NavigationItemPosition.BOTTOM,
            tooltip="Settings\nConfigure application appearance and behavior",
        )
        self.detail_window.add_settings_interface(settings_widget)

    def setup_tray(self):
        """Setup system tray icon."""
        self.tray_icon = QSystemTrayIcon(self.app)

        # Use Fluent Settings icon
        from qfluentwidgets import FluentIcon

        icon = FluentIcon.APPLICATION.icon()
        self.tray_icon.setIcon(icon)

        # Create tray menu
        tray_menu = QMenu()

        quit_action = QAction("Quit", self.app)
        quit_action.triggered.connect(self.shutdown)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.DoubleClick:
            self.show_window()

    def _on_settings_changed(self, category, key, value):
        """Handle settings changes."""
        if category == "appearance":
            self.sidebar_window.update_style()
            self.detail_window.update_style()
        elif category == "plugins":
            self.plugin_manager.refresh_plugin_state()

    def show_window(self):
        """Show the main window."""
        self.sidebar_window.show()
        self.sidebar_window.raise_()
        self.sidebar_window.activateWindow()

    def open_settings(self):
        """Open settings view."""
        self.show_window()
        # Navigate to settings in the window

    def run(self):
        """Start the application."""
        logger.info("Starting application...")
        # Start with just the sidebar visible? Or both?
        self.sidebar_window.show()

        # Check for plugin errors after showing window
        from PySide6.QtCore import QTimer

        QTimer.singleShot(500, self._check_plugin_errors)

        return self.app.exec()

    def _check_plugin_errors(self):
        """Check for errors and show dialog if any."""
        load_errors = self.plugin_manager.get_load_errors()
        if load_errors:
            # Use custom standalone dialog instead of MessageBox to avoid parent/mask issues
            w = PluginErrorDialog(load_errors)
            w.exec()

    def shutdown(self):
        """Shutdown the application."""
        logger.info("Shutting down...")

        # Shutdown plugins
        if hasattr(self, "plugin_manager"):
            self.plugin_manager.shutdown()

        # Close data service
        if hasattr(self, "data_service"):
            self.data_service.close()

        # Force close windows to bypass ignore() in closeEvent
        if hasattr(self, "sidebar_window"):
            self.sidebar_window.force_close()

        if hasattr(self, "detail_window"):
            self.detail_window.force_close()

        # Quit application
        self.app.quit()

        logger.info("Shutdown complete")


if __name__ == "__main__":
    app_instance = AgileTilesApp()

    # Make app_instance available globally for settings
    import __main__

    __main__.app_instance = app_instance

    sys.exit(app_instance.run())
