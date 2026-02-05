from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, TransparentToolButton
from qframelesswindow import FramelessWindow

from core.state_store import StateStore
from core.ui_kernel.theme_engine import ThemeEngine
from core.ui_kernel.view_host.card_lifecycle import CardLifecycle


class DetailWindow(FramelessWindow):
    """
    Content-only window. Appears next to sidebar.
    """

    def __init__(self, theme_engine: ThemeEngine, state_store: StateStore):
        super().__init__()
        self.theme_engine = theme_engine
        self.state_store = state_store

        # Window attributes
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Agile Tiles - Detail")

        # Setup UI
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 32, 0, 0)  # Reserve space for title bar
        self.vBoxLayout.setSpacing(0)

        # Customize Title Bar
        self.titleBar.raise_()
        self.titleBar.hBoxLayout.setContentsMargins(10, 0, 0, 0)
        self.titleBar.minBtn.hide()
        self.titleBar.maxBtn.hide()
        self.titleBar.closeBtn.hide()

        # Back Button
        self.back_btn = TransparentToolButton(FluentIcon.CLOSE, self.titleBar)
        self.back_btn.setFixedSize(30, 30)
        self.back_btn.clicked.connect(self.hide_content)
        self.titleBar.hBoxLayout.insertWidget(-1, self.back_btn)

        # Central Content
        self.stacked_widget = QStackedWidget(self)
        # Ensure stack is transparent
        self.stacked_widget.setStyleSheet("background: transparent;")
        self.vBoxLayout.addWidget(self.stacked_widget)

        # Cache style settings
        self._update_style()

        # Map IDs to indices
        self.plugin_widgets = {}

    def update_style(self):
        """Public method to refresh styles and repaint."""
        self._update_style()
        self.update()

    def _update_style(self):
        """Cache style settings to avoid reading state_store in paintEvent."""
        settings = self.state_store.get("settings", {}).get("appearance", {})
        self.cached_opacity = settings.get("sidebar_opacity", 0.9)

        self.cached_bg_color = QColor(32, 32, 32)  # Dark theme base
        if settings.get("theme_mode") == "light":
            self.cached_bg_color = QColor(255, 255, 255)
        self.cached_bg_color.setAlphaF(self.cached_opacity)

    def paintEvent(self, event):
        """Paint background with configured opacity."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Use cached values
        painter.setBrush(self.cached_bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)

    def add_plugin_interface(
        self, plugin_id: str, widget: QWidget, name: str, icon=None
    ):
        """Add plugin content to stack."""
        if not widget.objectName():
            widget.setObjectName(plugin_id.replace(".", "_") + "_widget")

        index = self.stacked_widget.addWidget(widget)
        self.plugin_widgets[plugin_id] = index

        # Restore state
        if isinstance(widget, CardLifecycle):
            try:
                state = self.state_store.get_plugin_state(plugin_id, "view_context", {})
                widget.restore_state(state)
            except Exception as e:
                print(f"Error restoring state: {e}")

    def remove_plugin_interface(self, plugin_id: str):
        """Remove plugin content from stack."""
        if plugin_id in self.plugin_widgets:
            index = self.plugin_widgets.pop(plugin_id)
            widget = self.stacked_widget.widget(index)
            self.stacked_widget.removeWidget(widget)
            widget.deleteLater()

    def add_settings_interface(self, widget: QWidget):
        """Add settings content."""
        index = self.stacked_widget.addWidget(widget)
        self.plugin_widgets["settings"] = index

    def show_plugin(self, plugin_id: str, anchor_rect=None):
        """Show specific plugin and position window."""
        if self.isVisible() and plugin_id in self.plugin_widgets:
            current_index = self.stacked_widget.currentIndex()
            target_index = self.plugin_widgets[plugin_id]
            if current_index == target_index:
                self.hide_content()
                return
        if plugin_id in self.plugin_widgets:
            self.stacked_widget.setCurrentIndex(self.plugin_widgets[plugin_id])

            # Position next to sidebar
            if anchor_rect:
                # anchor_rect is sidebar geometry
                width = 500  # Default width

                # Check sidebar position (Left vs Right)
                # If sidebar left is near 0, it's on the Left.
                if anchor_rect.left() < 50:
                    # Sidebar is Left -> Detail goes to Right
                    x = anchor_rect.right()
                else:
                    # Sidebar is Right -> Detail goes to Left
                    x = anchor_rect.left() - width

                # Vertical positioning
                from PySide6.QtGui import QGuiApplication

                # Determine screen based on anchor_rect (sidebar)
                screen = QGuiApplication.screenAt(anchor_rect.center())
                if not screen:
                    screen = QGuiApplication.primaryScreen()

                screen_geo = screen.availableGeometry()
                settings = self.state_store.get("settings", {}).get("appearance", {})
                min_height = settings.get("detail_min_height", 700)

                # Start with anchor top
                y = anchor_rect.top()
                height = max(anchor_rect.height(), min_height)

                # Ensure bottom doesn't exceed screen bottom
                if y + height > screen_geo.bottom():
                    # Shift up to fit
                    y = screen_geo.bottom() - height

                    # If shifting up makes it go off top, clamp to top and reduce height
                    if y < screen_geo.top():
                        y = screen_geo.top()
                        height = screen_geo.height()

                self.setGeometry(x, y, width, height)

            self.show()
            self.activateWindow()
        else:
            print(f"Plugin {plugin_id} not found")

    def hide_content(self):
        """Hide the detail window."""
        self.hide()

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
            self.hide()
