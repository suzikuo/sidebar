from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class LyricsWidget(QWidget):
    """
    A frameless, transparent, always-on-top window to display the text.
    It supports dragging anywhere on the window.
    """

    position_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bg_opacity = 100
        self._is_locked = False
        self._font_size = 16
        self._font_color = "#FFFFFF"
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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.label = QLabel(self)
        self.label.setText("Thief Book: 等待加载...")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Style the label to look like desktop lyrics
        self._update_label_style()

        layout.addWidget(self.label)

    def _update_label_style(self):
        font = QFont("Microsoft YaHei", self._font_size, QFont.Weight.Bold)
        self.label.setFont(font)
        self.label.setStyleSheet(f"color: {self._font_color};")

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
