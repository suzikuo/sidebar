from PySide6.QtCore import Qt, QTime, QTimer
from qfluentwidgets import StrongBodyLabel


class VerticalTimeWidget(StrongBodyLabel):
    """
    A widget that displays the current time vertically.
    Designed for use in the sidebar when it's hidden/peeking.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("color: white; background: transparent;")

        # Timer to update time every minute
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)  # Update every second for snappy response

        self.set_horizontal()

        self.update_time()

    def set_horizontal(self):
        self.arrangement = "Horizontal"  # 纵向排列

    def set_vertical(self):
        self.arrangement = "vertical"

    def update_time(self):
        """Update the label text with current time formatted vertically."""
        # Format HH:mm vertically: H\nH\n:\nm\nm
        current_time = QTime.currentTime().toString("HH:mm")
        if self.arrangement == "vertical":
            vertical_text = "".join(list(current_time))
        else:
            vertical_text = "\n".join(list(current_time))
        self.setText(vertical_text)
