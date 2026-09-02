from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class LyricsWidget(QWidget):
    """
    A frameless, transparent, always-on-top window to display the text.
    It supports dragging anywhere on the window.
    """

    position_changed = Signal(int, int)
    prev_clicked = Signal()
    next_clicked = Signal()
    close_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_opacity = 100
        self._is_locked = False
        self._font_size = 16
        self._font_color = "#FFFFFF"
        self._show_buttons = True
        self._init_ui()
        self._drag_pos = None

    def _init_ui(self):
        # Frameless, Always on Top, Tool (removes it from taskbar)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Transparent background
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.resize(800, 60)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(5)

        self.label = QLabel(self)
        self.label.setText("Thief Book: 等待加载...")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        main_layout.addWidget(self.label, 1)

        # ── Control Buttons ──
        self._btn_container = QWidget(self)
        self._btn_container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        btn_layout = QHBoxLayout(self._btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(2)

        self._prev_btn = QPushButton("↑", self._btn_container)
        self._prev_btn.setToolTip("上一页")
        self._prev_btn.clicked.connect(self.prev_clicked.emit)
        btn_layout.addWidget(self._prev_btn)

        self._next_btn = QPushButton("↓", self._btn_container)
        self._next_btn.setToolTip("下一页")
        self._next_btn.clicked.connect(self.next_clicked.emit)
        btn_layout.addWidget(self._next_btn)

        self._close_btn = QPushButton("×", self._btn_container)
        self._close_btn.setToolTip("关闭")
        self._close_btn.clicked.connect(self.close_clicked.emit)
        btn_layout.addWidget(self._close_btn)

        main_layout.addWidget(self._btn_container)

        # Style the label to look like desktop lyrics
        self._update_label_style()

    def _update_label_style(self):
        font = QFont("Microsoft YaHei", self._font_size, QFont.Weight.Bold)
        self.label.setFont(font)
        self.label.setStyleSheet(f"color: {self._font_color};")

        # Update button styles to match lyrics font color
        c = QColor(self._font_color)
        btn_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {self._font_color};
                border: none;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
                min-width: 24px;
                max-width: 24px;
                min-height: 24px;
                max-height: 24px;
            }}
            QPushButton:hover {{
                background-color: rgba({c.red()}, {c.green()}, {c.blue()}, 40);
            }}
            QPushButton:pressed {{
                background-color: rgba({c.red()}, {c.green()}, {c.blue()}, 80);
            }}
        """
        for btn in (self._prev_btn, self._next_btn, self._close_btn):
            btn.setStyleSheet(btn_style)

    def set_buttons_visible(self, visible: bool):
        """Show or hide the control buttons."""
        self._show_buttons = visible
        # When locked, always hide buttons regardless of the setting
        if self._is_locked:
            self._btn_container.setVisible(False)
        else:
            self._btn_container.setVisible(visible)

    def apply_config(self, config: dict):
        self._font_size = config.get("font_size", 16)
        self._font_color = config.get("font_color", "#FFFFFF")
        self._bg_opacity = config.get("bg_opacity", 100)

        self._update_label_style()

        is_locked = config.get("is_locked", False)
        if self._is_locked != is_locked:
            self._is_locked = is_locked
            flags = self.windowFlags()
            if is_locked:
                flags |= Qt.WindowType.WindowTransparentForInput
            else:
                flags &= ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.show()  # Required to apply flag changes on Windows

        # Update button visibility based on config and lock state
        show_buttons = config.get("show_buttons", True)
        self.set_buttons_visible(show_buttons)

        # Restore position if present
        if "window_x" in config and "window_y" in config:
            self.move(config["window_x"], config["window_y"])

        self.update()  # trigger paintEvent

    def set_text(self, text: str):
        self.label.setText(text)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._drag_pos is not None:
            self.position_changed.emit(self.x(), self.y())
        self._drag_pos = None
        event.accept()

    def paintEvent(self, event):
        """Optional: Draw a very subtle background/outline if hovered, mostly transparent."""
        super().paintEvent(event)
        if self._bg_opacity > 0:
            painter = QPainter(self)
            painter.fillRect(
                self.rect(), QColor(0, 0, 0, self._bg_opacity)
            )  # Semi-transparent black background
