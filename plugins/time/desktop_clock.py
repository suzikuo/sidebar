from PySide6.QtCore import Qt, QTime, QTimer, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

class DesktopClockWidget(QWidget):
    position_changed = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = 32
        self._font_color = "#FFFFFF"
        self._time_format = "HH:mm"
        self._is_locked = False
        self._alarm_manager = None
        self._tick_count = 0
        self._init_ui()
        self._drag_pos = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)

    def _init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.resize(300, 100)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_label_style()

        layout.addWidget(self.label)
        self.update_time()

    def set_alarm_manager(self, manager):
        self._alarm_manager = manager
        self.update_time()

    def _update_label_style(self):
        font = QFont("Microsoft YaHei", self._font_size, QFont.Weight.Bold)
        self.label.setFont(font)
        self.label.setStyleSheet(f"color: {self._font_color};")

    def apply_config(self, config: dict):
        self._time_format = config.get("format", "HH:mm")
        self._font_color = config.get("color", "white")
        self._font_size = config.get("desktop_font_size", 32)
        
        self._update_label_style()
        self.update_time()

        is_locked = config.get("desktop_locked", False)
        if self._is_locked != is_locked:
            self._is_locked = is_locked
            flags = self.windowFlags()
            if is_locked:
                flags |= Qt.WindowType.WindowTransparentForInput
            else:
                flags &= ~Qt.WindowType.WindowTransparentForInput
            self.setWindowFlags(flags)
            self.show()

        if "desktop_x" in config and "desktop_y" in config:
            self.move(config["desktop_x"], config["desktop_y"])

    def update_time(self):
        self._tick_count += 1
        alarm_info = None
        if self._alarm_manager:
            alarm_info = self._alarm_manager.get_next_alarm_info()

        if alarm_info and alarm_info["remaining_seconds"] <= 5 * 60:
            remaining = max(0, int(alarm_info["remaining_seconds"]))
            mins = remaining // 60
            secs = remaining % 60
            countdown_str = f"⏱️ {mins}:{secs:02d}"
            
            # Flash text
            if (self._tick_count % 2) == 0:
                self.label.setStyleSheet("color: #FFB900;")
            else:
                self.label.setStyleSheet(f"color: {self._font_color};")

            current_time = QTime.currentTime().toString(self._time_format)
            self.label.setText(f"{countdown_str} | {current_time}")
        else:
            self.label.setStyleSheet(f"color: {self._font_color};")
            self.label.setText(QTime.currentTime().toString(self._time_format))

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
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
        super().paintEvent(event)
        # Optional: draw subtle background if needed
        # painter = QPainter(self)
        # painter.fillRect(self.rect(), QColor(0, 0, 0, 50))
