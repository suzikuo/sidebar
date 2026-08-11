from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon, TransparentToolButton

from core.logger import logger
from core.state_store import StateStore
from core.ui_kernel.theme_engine import ThemeEngine
from core.ui_kernel.view_host.card_lifecycle import CardLifecycle

from .FramelessWindow import FramelessWindow


class DetailWindow(FramelessWindow):
    """
    Content-only window. Appears next to sidebar.
    """

    plugin_view_failed = Signal(str, str)

    def __init__(self, theme_engine: ThemeEngine, state_store: StateStore):
        super().__init__()
        self.theme_engine = theme_engine
        self.state_store = state_store

        # Window attributes
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setWindowTitle("Agile Tiles - Detail")

        # Enable window resizing
        self.setResizeEnabled(True)

        # Set minimum size to ensure usability
        self.setMinimumSize(400, 300)

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

        # Plugin metadata is cheap; detail widgets are created on first use.
        self.plugin_widgets = {}
        self.plugin_factories = {}

    def update_style(self):
        """Public method to refresh styles and repaint."""
        self._update_style()
        self.update()

    def _update_style(self):
        """Cache style settings to avoid reading state_store in paintEvent."""
        settings = self.state_store.get("settings", {}).get("appearance", {})
        self.cached_opacity = settings.get("detail_bg_opacity", 0.9)

        self.cached_bg_color = QColor(32, 32, 32)  # Dark theme base
        if settings.get("theme_mode") == "light":
            self.cached_bg_color = QColor(255, 255, 255)
        self.cached_bg_color.setAlphaF(self.cached_opacity)

    def paintEvent(self, event):
        """Paint background with configured opacity."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Clear background and replace with current opacity
        painter.setCompositionMode(QPainter.CompositionMode_Source)

        # Use cached values
        painter.setBrush(self.cached_bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect(), 10, 10)

    def add_plugin_interface(
        self, plugin_id: str, widget: QWidget, name: str, icon=None
    ):
        """Add plugin content to stack."""
        del icon
        self._install_plugin_widget(plugin_id, widget)

    def add_plugin_interface_factory(self, plugin_id: str, factory, name: str):
        """Register a plugin view without constructing its QWidget yet."""
        if not callable(factory):
            raise TypeError("Plugin view factory must be callable")
        self.plugin_factories[plugin_id] = (factory, name)

    def _install_plugin_widget(self, plugin_id: str, widget: QWidget):
        if not isinstance(widget, QWidget):
            raise TypeError(f"Plugin {plugin_id} did not return a QWidget")
        if not widget.objectName():
            widget.setObjectName(plugin_id.replace(".", "_") + "_widget")

        self.stacked_widget.addWidget(widget)
        self.plugin_widgets[plugin_id] = widget

        # Restore state
        if isinstance(widget, CardLifecycle):
            try:
                state = self.state_store.get_plugin_state(plugin_id, "view_context", {})
                widget.restore_state(state)
            except Exception as e:
                logger.error(
                    f"Error restoring state for {plugin_id}: {e}", exc_info=True
                )
        return widget

    def _ensure_plugin_interface(self, plugin_id: str):
        widget = self.plugin_widgets.get(plugin_id)
        if widget is not None:
            return widget
        registration = self.plugin_factories.get(plugin_id)
        if registration is None:
            return None
        factory, name = registration
        try:
            return self._install_plugin_widget(plugin_id, factory())
        except Exception as error:
            logger.error(
                "Failed to create plugin view for %s.",
                plugin_id,
                exc_info=True,
            )
            self.plugin_view_failed.emit(plugin_id, str(error))
            placeholder = BodyLabel(f"{name} 界面加载失败：{error}", self)
            placeholder.setWordWrap(True)
            placeholder.setAlignment(Qt.AlignCenter)
            return self._install_plugin_widget(plugin_id, placeholder)

    def remove_plugin_interface(self, plugin_id: str):
        """Remove plugin content from stack."""
        self.plugin_factories.pop(plugin_id, None)
        widget = self.plugin_widgets.pop(plugin_id, None)
        if widget is not None:
            self.stacked_widget.removeWidget(widget)
            widget.deleteLater()

    def add_settings_interface(self, widget: QWidget):
        """Add settings content."""
        self._install_plugin_widget("settings", widget)

    def show_plugin(self, plugin_id: str, anchor_rect=None):
        """Show specific plugin and position window."""
        target_widget = self._ensure_plugin_interface(plugin_id)
        if self.isVisible() and target_widget is not None:
            if self.stacked_widget.currentWidget() is target_widget:
                self.hide_content()
                return
        if target_widget is not None:
            self.stacked_widget.setCurrentWidget(target_widget)

            # Position relative to sidebar
            if anchor_rect:
                from PySide6.QtGui import QGuiApplication

                # Determine screen based on anchor_rect (sidebar)
                screen = QGuiApplication.screenAt(anchor_rect.center())
                if not screen:
                    screen = QGuiApplication.primaryScreen()

                screen_geo = screen.availableGeometry()
                settings = self.state_store.get("settings", {}).get("appearance", {})
                sidebar_position = settings.get("sidebar_position", "right")

                # Check if sidebar is at top
                if sidebar_position == "top" or anchor_rect.top() < 50:
                    # Sidebar is at top -> Detail goes below
                    width = anchor_rect.width()  # Match sidebar width
                    min_height = settings.get("detail_min_height", 700)

                    x = anchor_rect.left()
                    y = anchor_rect.bottom()
                    height = min(min_height, screen_geo.bottom() - y)

                    self.setGeometry(x, y, width, height)
                else:
                    # Sidebar is left/right -> Detail goes beside
                    width = 500  # Default width

                    # Check sidebar position (Left vs Right)
                    if anchor_rect.left() < 50:
                        # Sidebar is Left -> Detail goes to Right
                        x = anchor_rect.right()
                    else:
                        # Sidebar is Right -> Detail goes to Left
                        x = anchor_rect.left() - width

                    # Vertical positioning
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
            logger.warning(f"Plugin {plugin_id} not found")

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
