from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout
from qfluentwidgets import (
    Action,
    FluentIcon,
    NavigationInterface,
    NavigationItemPosition,
    RoundMenu,
)
from qframelesswindow import FramelessWindow

from core.state_store import StateStore
from ui.components.time_widget import VerticalTimeWidget

from .window_behavior import WindowBehavior


class SidebarWindow(FramelessWindow):
    """
    Independent Sidebar Window.
    - Hosts the NavigationInterface (Icons).
    - Handles Edge Docking (Hidden <-> Visible).
    - Signals DetailWindow to show content.
    """

    # Signal emitted when a navigation item is clicked
    # args: route_key (str)
    plugin_selected = Signal(str)

    # Signal emitted for left-click "action" (e.g. run)
    plugin_action_triggered = Signal(str)

    def __init__(self, state_store: StateStore):
        super().__init__()
        self.state_store = state_store
        self.detail_window = None  # Logic coordination
        self.peek_width = 1

        # 1. Setup UI
        # User requested to remove the "three bars" menu button
        self.navigationInterface = NavigationInterface(
            self, showMenuButton=False, showReturnButton=False
        )

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addWidget(self.navigationInterface)
        # Ensure NavigationInterface doesn't paint over our custom background
        self.navigationInterface.setStyleSheet(
            "NavigationInterface { background: transparent; }"
        )

        # Time Widget (Vertical)
        self.timeWidget = VerticalTimeWidget(self)
        self.vBoxLayout.addStretch(1)
        self.vBoxLayout.addWidget(self.timeWidget)
        self.vBoxLayout.addSpacing(20)  # Bottom margin

        # 2. Window Flags & Attributes
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        # 3. Behavior Logic
        self.setResizeEnabled(False)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        # Ensure window can shrink below children's minimum size if needed
        self.setMinimumHeight(0)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._perform_hide)

        # Scrolling/Dragging state
        self._is_dragging = False
        self._drag_start_y = 0
        self._initial_y_offset = 0

        # 4. Initial State
        self.is_hidden = True
        self.items = {}
        self.item_data = {}  # Store metadata for reconstruction
        self._update_style()  # Cache style settings
        self._init_behavior()
        # Timers removed in favor of events
        self._setup_connections()

        self.navigationInterface.hide()

        self.setGeometry(self.behavior.get_hidden_geometry(peek_width=self.peek_width))

        self.titleBar.hide()

    def update_style(self):
        """Public method to refresh styles and repaint."""
        self._update_style()

        # Apply new geometry based on current state
        if not self.is_hidden:
            self.behavior = self._get_behavior(is_hidden=False)
            self.setGeometry(self.behavior.get_visible_geometry())
        else:
            self.behavior = self._get_behavior(is_hidden=True)
            self.setGeometry(
                self.behavior.get_hidden_geometry(peek_width=self.peek_width)
            )

        self.update()

    def _update_style(self):
        """Cache style settings to avoid reading state_store in paintEvent."""
        settings = self.state_store.get("settings", {}).get("appearance", {})
        self.cached_opacity = settings.get("sidebar_opacity", 0.9)

        is_light = settings.get("theme_mode") == "light"
        self.cached_bg_color = QColor(32, 32, 32)  # Dark theme base
        if is_light:
            self.cached_bg_color = QColor(255, 255, 255)
        self.cached_bg_color.setAlphaF(self.cached_opacity)

        # Update TimeWidget theme and visibility
        if hasattr(self, "timeWidget"):
            # Check visibility setting
            general_settings = self.state_store.get("settings", {}).get("general", {})
            show_time = general_settings.get("show_time", True)
            self.timeWidget.setVisible(show_time)



    def set_detail_window(self, window):
        """Set reference to detail window for coordinated hiding."""
        self.detail_window = window

    def paintEvent(self, event):
        """Paint background with configured opacity."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Use cached values
        painter.setBrush(self.cached_bg_color)

        # Draw overall border (always visible)
        settings = self.state_store.get("settings", {}).get("appearance", {})
        
        # Determine border color based on theme (light vs dark)
        # Check if background is light (assuming light theme has light bg)
        is_light_bg = self.cached_bg_color.lightness() > 128
        default_border = "#C0C0C0" if is_light_bg else "#404040"
        
        border_color = settings.get("sidebar_border_color", default_border)
        painter.setPen(QPen(QColor(border_color), 1))
        
        # Adjust rect to avoid clipping the border
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 10, 10)

    def _get_behavior(self, is_hidden=False):
        """Get window behavior based on state (hidden/visible)."""
        # 1. Determine which screen we are on
        # If we have a geometry, use the screen that contains our center
        # Otherwise fall back to primary screen
        current_geo = self.geometry()
        screen = QGuiApplication.screenAt(current_geo.center())
        if not screen:
            screen = QGuiApplication.primaryScreen()

        screen_geometry = screen.availableGeometry()

        # 2. Read settings
        settings = self.state_store.get("settings", {}).get("appearance", {})
        y_offset_px = settings.get("sidebar_y_offset", 0)
        edge = settings.get("sidebar_position", "right")

        if is_hidden:
            height_percent = settings.get("sidebar_hidden_height_percent", 0.8)
        else:
            height_percent = settings.get("sidebar_height_percent", 0.8)

        # 3. Calculate height
        height = int(screen_geometry.height() * height_percent)

        # 4. Construct a "virtual screen" rect that is centered vertically + offset
        # We calculate the Y relative to the screen's top
        base_y = (screen_geometry.height() - height) // 2
        final_y = screen_geometry.top() + base_y + y_offset_px

        # Clamp final_y to keep window on screen vertically
        final_y = max(
            screen_geometry.top(), min(final_y, screen_geometry.bottom() - height)
        )

        virtual_screen = QRect(
            screen_geometry.left(),
            final_y,
            screen_geometry.width(),
            height,
        )

        return WindowBehavior(
            screen_geometry=virtual_screen,
            width=48,  # Sidebar is fixed width (icon strip)
            collapsed_width=48,
            edge=edge,
        )

    def _init_behavior(self):
        """Legacy init helper."""
        self.behavior = self._get_behavior(is_hidden=self.is_hidden)

    # _init_timers removed

    # _check_edge_trigger removed

    # _check_auto_hide removed

    def _setup_connections(self):
        # Forward navigation clicks
        self.navigationInterface.installEventFilter(self)

    def add_item(
        self,
        route_key: str,
        icon,
        text: str,
        position=NavigationItemPosition.TOP,
        tooltip: str = None,
    ):
        """Add item to navigation."""
        item = self.navigationInterface.addItem(
            routeKey=route_key,
            icon=icon,
            text=text,
            onClick=None,  # Handled in eventFilter
            position=position,
        )
        item.setToolTip(tooltip or text)
        self.items[route_key] = item

        # Connect signals
        # Install event filter to catch right clicks
        item.installEventFilter(self)

        # Store metadata for reordering
        self.item_data[route_key] = {
            "icon": icon,
            "text": text,
            "tooltip": tooltip,
            "position": position,
        }

    def remove_item(self, route_key: str):
        """Remove item from navigation."""
        if route_key in self.items:
            item = self.items.pop(route_key)
            if item:
                item.deleteLater()

        if route_key in self.item_data:
            del self.item_data[route_key]

    def update_plugin_order(self, ordered_ids: list):
        """Reorder plugin items (Position.TOP) according to the list.

        Args:
            ordered_ids: List of route_keys in desired order.
        """
        # 1. Identify items to reorder (only plugins/TOP items)
        # We assume anything in ordered_ids is a plugin and uses SCROLL/TOP position

        # We need to preserve the Settings item (BOTTOM) and potentially others not involved.
        # But for simplicity, we can remove ALL TOP items and re-add them.

        # Snapshot current items

        # Filter strictly for things in our managed list OR things that are clearly plugins
        # For now, let's process the ordered_ids.

        added_keys = set()

        # Remove all affected items first to clear the slate
        # Logic: Remove item from UI, but keep metadata for re-adding

        # It's tricky to remove from layout without visual glitch, but acceptable for settings change.
        # We walk through ordered_ids. If it exists in self.items, we remove and re-add.
        # But simply removing and adding might put them at the end of the "TOP" list.
        # So we really need to remove ALL TOP-positioned items first, then re-add them in order.

        # Find all plugin keys (assuming they are the ones in ordered_ids + any others leftovers)
        # Better: Identify all items with Position.TOP? NavigationInterface doesn't expose it easily?
        # We stored it in self.item_data!

        keys_to_reorder = [
            k
            for k, v in self.item_data.items()
            if v.get("position") == NavigationItemPosition.TOP
        ]

        # Remove them from UI
        for k in keys_to_reorder:
            # Use official API to remove from NavigationInterface internals
            self.navigationInterface.removeWidget(k)

            # Clean up our own reference and ensure deletion
            if k in self.items:
                item = self.items.pop(k)
                item.deleteLater()

        # Re-add in order
        # 1. Add explicitly ordered items
        for pid in ordered_ids:
            if pid in self.item_data:
                self._add_item_from_data(pid)
                added_keys.add(pid)

        # 2. Add any leftovers (plugins that might not be in the order list for some reason)
        for k in keys_to_reorder:
            if k not in added_keys:
                self._add_item_from_data(k)

    def _add_item_from_data(self, route_key):
        """Helper to add item using stored data."""
        data = self.item_data.get(route_key)
        if not data:
            return

        item = self.navigationInterface.addItem(
            routeKey=route_key,
            icon=data["icon"],
            text=data["text"],
            onClick=None,
            position=data["position"],
        )

        # Check if item creation failed
        if item is None:
            print(
                f"[AgileTiles] Warning: Failed to re-add navigation item: {route_key}"
            )
            return

        item.setToolTip(data.get("tooltip") or data["text"])
        self.items[route_key] = item
        item.installEventFilter(self)

    def eventFilter(self, obj, event):
        """Handle internal events and context menus."""
        # Find which item this belongs to
        route_key = next((k for k, v in self.items.items() if v is obj), None)

        if route_key and event.type() == QEvent.MouseButtonRelease:
            if event.button() == Qt.RightButton:
                self._show_context_menu(route_key, event.globalPos())
                return True
            elif event.button() == Qt.LeftButton:
                self.plugin_action_triggered.emit(route_key)
                return True

        return super().eventFilter(obj, event)

    # Signal emitted to request context menu population
    # args: plugin_id (str), menu (RoundMenu)
    populate_context_menu = Signal(str, object)

    def _show_context_menu(self, route_key, pos):
        """Show context menu for a plugin item."""
        menu = RoundMenu(parent=self)

        # Determine display name
        item = self.items.get(route_key)
        name = item.text() if item else route_key

        openAction = Action(FluentIcon.TILES, f"Open {name}", self)
        openAction.triggered.connect(lambda: self.plugin_selected.emit(route_key))

        runAction = Action(FluentIcon.PLAY, "Execute", self)
        runAction.triggered.connect(
            lambda: self.plugin_action_triggered.emit(route_key)
        )

        menu.addAction(openAction)
        menu.addAction(runAction)

        # Emit signal to request additional items
        self.populate_context_menu.emit(route_key, menu)

        menu.exec(pos)

    def mousePressEvent(self, event):
        """Handle start of vertical dragging."""
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._drag_start_y = event.globalPosition().y()
            self._initial_y_offset = (
                self.state_store.get("settings", {})
                .get("appearance", {})
                .get("sidebar_y_offset", 0)
            )
            # Temporarily stop hide timer while dragging
            self.hide_timer.stop()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle vertical dragging and position update."""
        if self._is_dragging:
            delta_y = int(event.globalPosition().y() - self._drag_start_y)
            new_offset = self._initial_y_offset + delta_y

            # Update settings immediately for smooth visual feedback
            # OR just update the geometry directly. Updating settings and calling update_style
            # might be slightly heavier but ensures consistency.
            self.state_store.get("settings", {})["appearance"]["sidebar_y_offset"] = (
                new_offset
            )

            # Update behavior and geometry
            self.behavior = self._get_behavior(is_hidden=self.is_hidden)
            if self.is_hidden:
                self.setGeometry(
                    self.behavior.get_hidden_geometry(peek_width=self.peek_width)
                )
            else:
                self.setGeometry(self.behavior.get_visible_geometry())

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Finalize dragging and persist settings."""
        if self._is_dragging and event.button() == Qt.LeftButton:
            self._is_dragging = False

            # Persist to state store (atomic save)
            self.state_store.save()

        super().mouseReleaseEvent(event)

    def expand(self):
        """Expand the sidebar to full visibility."""
        self.hide_timer.stop()
        if self.is_hidden:
            self.navigationInterface.show()
            self.behavior = self._get_behavior(is_hidden=False)
            geom = self.behavior.get_visible_geometry()
            self.setGeometry(geom)
            self.is_hidden = False

    def collapse(self):
        """Collapse the sidebar to peek mode."""
        # Double check mouse position or other logic if needed, but this is a forced collapse
        self.navigationInterface.hide()
        self.behavior = self._get_behavior(is_hidden=True)
        geom = self.behavior.get_hidden_geometry(peek_width=self.peek_width)
        self.setGeometry(geom)
        self.is_hidden = True

        # Also hide Detail Window
        if self.detail_window:
            self.detail_window.hide_content()

    def enterEvent(self, event):
        """Mouse enter: expand sidebar."""
        self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event):
        """Mouse leave: start hide timer."""
        # Check if moving to detail window before hiding?
        # Ideally detail window also cancels the timer if entered.
        # For now, just start timer. The delay gives user time to move.
        delay_ms = (
            self.state_store.get("settings", {})
            .get("general", {})
            .get("auto_hide_delay", 1000)
        )
        self.hide_timer.start(delay_ms)
        super().leaveEvent(event)

    def _perform_hide(self):
        """Execute the hide action."""
        # Double check if we should really hide (e.g. detailed window is focused)
        if self.detail_window and self.detail_window.isActiveWindow():
            return

        # Check if mouse is actually in sidebar (race condition with fast moves)
        if self.frameGeometry().contains(self.cursor().pos()):
            return

        # If Detail Window is open, don't hide sidebar
        if self.detail_window and self.detail_window.isVisible():
            self.hide_timer.start(
                self.state_store.get("settings", {})
                .get("general", {})
                .get("auto_hide_delay", 1000)
            )
            return

        self.collapse()

    def force_close(self):
        """Force close the window."""
        self._is_force_closing = True
        self.close()

    def closeEvent(self, event):
        """Handle close event."""
        if getattr(self, "_is_force_closing", False):
            event.accept()
        else:
            event.ignore()
            # Just hide? Or do nothing if it's the main window?
            # Sidebar usually stays open or hides.
            # If default behavior is desired, maybe don't override?
            # But to be safe against accidental closes:
            self.setGeometry(self.behavior.get_hidden_geometry())
            self.is_hidden = True

    @property  # Helper for external coordination
    def geometry_rect(self):
        return self.frameGeometry()
