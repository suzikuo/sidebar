from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    Action,
    FluentIcon,
    NavigationInterface,
    NavigationItemPosition,
    RoundMenu,
)

from core.logger import logger
from core.state_store import StateStore
from core.window_system.horizontal_navigation import HorizontalNavigationInterface

from .window_behavior import WindowBehavior


class SidebarWindow(QWidget):
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

        # Get peek_width from settings
        settings = self.state_store.get("settings", {}).get("appearance", {})
        self.peek_width = settings.get("peek_width", 2)

        # Determine edge position from settings BEFORE creating layout
        settings = self.state_store.get("settings", {}).get("appearance", {})
        self.edge = settings.get("sidebar_position", "right")

        # 1. Setup UI based on edge position
        if self.edge == "top":
            self.navigationInterface = HorizontalNavigationInterface(
                self, showMenuButton=False, showReturnButton=False
            )

            self.vBoxLayout = QHBoxLayout(self)
            self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
            self.vBoxLayout.addWidget(self.navigationInterface)

            self.vBoxLayout.addStretch(1)
            self.vBoxLayout.addSpacing(20)  # Bottom margin

        else:
            # Vertical layout for left/right position - use NavigationInterface
            self.navigationInterface = NavigationInterface(
                self, showMenuButton=False, showReturnButton=False
            )

            self.vBoxLayout = QVBoxLayout(self)
            self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
            self.vBoxLayout.addWidget(self.navigationInterface)

            self.vBoxLayout.addStretch(1)
            self.vBoxLayout.addSpacing(20)  # Bottom margin

        # Force transparent background on all child widgets
        self.navigationInterface.setStyleSheet("""
            NavigationInterface, HorizontalNavigationInterface, QWidget, QScrollArea, QFrame {
                background: transparent;
                background-color: transparent;
            }
            
            ToolButton[isSelected=true] {
                background-color: rgba(255, 107, 157, 0.2);
                border-bottom: 2px solid #FF6B9D;
            }
        """)

        # 2. Window Flags & Attributes
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        # 3. Behavior Logic
        # self.setResizeEnabled(False)
        self.setMouseTracking(True)
        # Ensure window can shrink below children's minimum size if needed
        if self.edge == "top":
            self.setMinimumWidth(0)
        else:
            self.setMinimumHeight(0)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._perform_hide)

        # Scrolling/Dragging state (supports both vertical and horizontal)
        self._is_dragging = False
        self._drag_start_y = 0
        self._drag_start_x = 0
        self._initial_y_offset = 0
        self._initial_x_offset = 0

        # 4. Initial State
        self.is_hidden = True
        self.items = {}
        self.item_data = {}  # Store metadata for reconstruction
        self._update_style()  # Cache style settings
        self._init_behavior()
        # Timers removed in favor of events
        self._setup_connections()

        self.navigationInterface.hide()

        # Container for plugin sidebar widgets (e.g. lyrics)
        self._sidebar_widgets: list[QWidget] = []

        self.setGeometry(self.behavior.get_hidden_geometry(peek_width=self.peek_width))

        # self.titleBar.hide()

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

    def add_sidebar_widget(self, widget: QWidget):
        """Insert a plugin-provided widget into the sidebar layout."""
        # 1. Inform widget of current orientation if it cares
        if hasattr(widget, "set_orientation"):
            widget.set_orientation(self.edge)

        # 2. Insert into layout
        # Layout order: navigationInterface, [sidebar widgets…], stretch, spacing
        # We insert before the stretch (which is the last item before spacing)
        # However, to be safe, we can just insert after navigationInterface (idx 1)
        # or before the stretch if we can find it.
        # Let's find the stretch index.
        idx = self.vBoxLayout.count() - 2  # Before stretch and spacing
        if idx > 0:
            self.vBoxLayout.insertWidget(idx, widget)
        else:
            self.vBoxLayout.addWidget(widget)
        self._sidebar_widgets.append(widget)

    def _update_style(self):
        """Cache style settings to avoid reading state_store in paintEvent."""
        settings = self.state_store.get("settings", {}).get("appearance", {})
        self.cached_opacity = settings.get("sidebar_bg_opacity", 0.9)

        # Update edge orientation
        old_edge = self.edge
        self.edge = settings.get("sidebar_position", "right")

        if old_edge != self.edge:
            # Notify widgets of orientation change
            for widget in self._sidebar_widgets:
                if hasattr(widget, "set_orientation"):
                    widget.set_orientation(self.edge)

        is_light = settings.get("theme_mode") == "light"
        self.cached_bg_color = QColor(32, 32, 32)  # Dark theme base
        if is_light:
            self.cached_bg_color = QColor(255, 255, 255)
        # Only set alpha on background color, not the entire window
        # This keeps content (icons, text) opaque while background is transparent
        self.cached_bg_color.setAlphaF(self.cached_opacity)

    def set_detail_window(self, window):
        """Set reference to detail window for coordinated hiding."""
        self.detail_window = window

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1️⃣ 先清空窗口缓冲区（这是 Source 的唯一正确用途）
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.transparent)

        # 2️⃣ 切回正常混合模式
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # 3️⃣ 画半透明背景
        bg = QColor(self.cached_bg_color)
        # 这里用 cached_bg_color 自带的 alpha 就行
        painter.setBrush(bg)

        # 4️⃣ 边框（不透明 or 轻微 alpha 都 OK）
        settings = self.state_store.get("settings", {}).get("appearance", {})
        is_light_bg = bg.lightness() > 128
        default_border = "#C0C0C0" if is_light_bg else "#404040"
        border_color = settings.get("sidebar_border_color", default_border)

        painter.setPen(QPen(QColor(border_color), 1))

        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 10, 10)

    def _get_behavior(self, is_hidden=False):
        """Get window behavior based on state (hidden/visible)."""
        # 1. Determine which screen we are on
        current_geo = self.geometry()
        screen = QGuiApplication.screenAt(current_geo.center())
        if not screen:
            screen = QGuiApplication.primaryScreen()

        screen_geometry = screen.availableGeometry()

        # 2. Read settings
        settings = self.state_store.get("settings", {}).get("appearance", {})
        edge = settings.get("sidebar_position", "right")

        # 3. Calculate dimensions based on edge position
        if edge == "top":
            # Horizontal layout for top edge
            x_offset_px = settings.get("sidebar_x_offset", 0)

            # In horizontal mode, use height_percent settings to control width
            # This makes the settings UI consistent (height slider controls the variable dimension)
            if is_hidden:
                width_percent = settings.get("sidebar_hidden_height_percent", 0.8)
            else:
                width_percent = settings.get("sidebar_height_percent", 0.8)

            width = int(screen_geometry.width() * width_percent)

            # Center horizontally + offset
            base_x = (screen_geometry.width() - width) // 2
            final_x = screen_geometry.left() + base_x + x_offset_px

            # Clamp to keep on screen
            final_x = max(
                screen_geometry.left(), min(final_x, screen_geometry.right() - width)
            )

            virtual_screen = QRect(
                final_x,
                screen_geometry.top(),
                width,
                screen_geometry.height(),
            )
        else:
            # Vertical layout for left/right edge
            y_offset_px = settings.get("sidebar_y_offset", 0)

            if is_hidden:
                height_percent = settings.get("sidebar_hidden_height_percent", 0.8)
            else:
                height_percent = settings.get("sidebar_height_percent", 0.8)

            height = int(screen_geometry.height() * height_percent)

            # Center vertically + offset
            base_y = (screen_geometry.height() - height) // 2
            final_y = screen_geometry.top() + base_y + y_offset_px

            # Clamp to keep on screen
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
            width=48,
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

        # For left/right position, use NavigationInterface
        item = self.navigationInterface.addItem(
            routeKey=route_key,
            icon=icon,
            text=text,
            onClick=None,  # Handled in eventFilter
            position=position,
        )
        item.setToolTip(tooltip or text)
        self.items[route_key] = item

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
            logger.warning(f"Failed to re-add navigation item: {route_key}")
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
        """Handle start of dragging (vertical or horizontal based on position)."""
        if event.button() == Qt.LeftButton:
            enable_hover = (
                self.state_store.get("settings", {})
                .get("general", {})
                .get("enable_mouse_hover", True)
            )
            if enable_hover:
                self._is_dragging = True

            # Store both X and Y positions
            self._drag_start_y = event.globalPosition().y()
            self._drag_start_x = event.globalPosition().x()

            settings = self.state_store.get("settings", {}).get("appearance", {})
            self._initial_y_offset = settings.get("sidebar_y_offset", 0)
            self._initial_x_offset = settings.get("sidebar_x_offset", 0)

            self.hide_timer.stop()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle dragging and position update (vertical or horizontal based on position)."""
        if self._is_dragging:
            settings = self.state_store.get("settings", {}).get("appearance", {})
            edge = settings.get("sidebar_position", "right")

            if edge == "top":
                # Horizontal dragging for top position
                delta_x = int(event.globalPosition().x() - self._drag_start_x)
                new_offset = self._initial_x_offset + delta_x
                self.state_store.get("settings", {})["appearance"][
                    "sidebar_x_offset"
                ] = new_offset
            else:
                # Vertical dragging for left/right position
                delta_y = int(event.globalPosition().y() - self._drag_start_y)
                new_offset = self._initial_y_offset + delta_y
                self.state_store.get("settings", {})["appearance"][
                    "sidebar_y_offset"
                ] = new_offset

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
        # self.hide()
        self.behavior = self._get_behavior(is_hidden=True)
        geom = self.behavior.get_hidden_geometry(peek_width=self.peek_width)
        self.setGeometry(geom)
        self.is_hidden = True

        # Also hide Detail Window
        if self.detail_window:
            self.detail_window.hide_content()

    def enterEvent(self, event):
        """Mouse enter: expand sidebar."""
        # Check setting before expanding
        enable_hover = (
            self.state_store.get("settings", {})
            .get("general", {})
            .get("enable_mouse_hover", True)
        )
        # If already visible, we must ensure timer is stopped (call expand)
        # If hidden, only expand if setting is enabled
        if not self.is_hidden or enable_hover:
            self.expand()

        super().enterEvent(event)

    def leaveEvent(self, event):
        """Mouse leave: start hide timer only if edge-hide is enabled."""
        enable_hover = (
            self.state_store.get("settings", {})
            .get("general", {})
            .get("enable_mouse_hover", True)
        )
        if not enable_hover:
            # Feature disabled — sidebar stays expanded, do not auto-hide
            super().leaveEvent(event)
            return

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
