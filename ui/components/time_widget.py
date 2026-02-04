from PySide6.QtCore import Qt, QTime, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel


class VerticalTimeWidget(QLabel):
    """
    A widget that displays the current time vertically.
    Designed for use in the sidebar when it's hidden/peeking.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("color: white; background: transparent;")

        # Use a clean, modern font
        font = QFont("Segoe UI", 10, QFont.Bold)
        self.setFont(font)

        # Timer to update time every minute
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)  # Update every second for snappy response

        self.update_time()

    def update_time(self):
        """Update the label text with current time formatted vertically."""
        current_time = QTime.currentTime().toString("HH:mm")
        # Format HH:mm vertically: H\nH\n:\nm\nm
        vertical_text = "\n".join(list(current_time))
        self.setText(vertical_text)

    def set_theme(self, is_dark: bool):
        """Update color based on theme."""
        color = "white" if is_dark else "black"
        self.setStyleSheet(f"color: {color}; background: transparent;")
