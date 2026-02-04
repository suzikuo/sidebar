"""
Shortcut Picker Widget
Allows users to record a key sequence for shortcuts.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout


class ShortcutPickerButton(QPushButton):
    """
    A button that displays the current shortcut and allows recording a new one.
    """

    shortcutChanged = Signal(str)

    def __init__(self, current_shortcut="None", parent=None):
        super().__init__(parent)
        self.current_shortcut = current_shortcut or "None"
        self.setText(self.current_shortcut.upper())
        self.setFixedWidth(120)
        self.clicked.connect(self._start_recording)

    def _start_recording(self):
        """Open a dialog or enter recording mode."""
        self.setText("Press keys...")
        self.setEnabled(False)

        # Open a modal dialog to capture keys
        recorder = ShortcutRecorderDialog(self.window())
        if recorder.exec():
            new_shortcut = recorder.selected_shortcut
            # Allow empty string (cleared), but not None (cancelled)
            if new_shortcut is not None:
                self.current_shortcut = new_shortcut
                display_text = new_shortcut.upper() if new_shortcut else "None"
                self.setText(display_text)
                self.shortcutChanged.emit(new_shortcut)
        else:
            display_text = (
                self.current_shortcut.upper() if self.current_shortcut else "None"
            )
            self.setText(display_text)

        self.setEnabled(True)


class ShortcutRecorderDialog(QDialog):
    """
    Dialog to capture key presses.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Record Shortcut")
        self.setFixedSize(300, 150)

        layout = QVBoxLayout(self)

        self.label = QLabel("Press a key combination...", self)
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        # Clear button
        self.clear_btn = QPushButton("Clear / None", self)
        self.clear_btn.clicked.connect(self._clear)
        layout.addWidget(self.clear_btn)

        # Cancel button
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.clicked.connect(self.reject)
        layout.addWidget(self.cancel_btn)

        self.selected_shortcut = None
        self.modifiers = set()

    def keyPressEvent(self, event):
        """Capture key press."""
        key = event.key()
        if key == Qt.Key_Escape:
            self.reject()
        # Ignore modifier keys (Control, Shift, Alt, Meta)
        # We only want to trigger when a non-modifier key is pressed
        if key in (
            Qt.Key_Control,
            Qt.Key_Shift,
            Qt.Key_Alt,
            Qt.Key_Meta,
            Qt.Key_Super_L,
            Qt.Key_Super_R,
        ):
            return

        # Ignore modifier-only presses for final result, but track them if needed
        # Actually keyboard library uses strings like "ctrl+alt+a"
        # We need to map Qt keys to keyboard library strings

        # Use QKeyCombination explicitly
        from PySide6.QtCore import QKeyCombination

        combo = QKeyCombination(event.modifiers(), Qt.Key(key))
        sequence = QKeySequence(combo)
        text = sequence.toString(QKeySequence.PortableText).lower()

        # Fix some Qt discrepancies if needed
        # e.g. "meta" -> "windows"

        self.selected_shortcut = text
        self.accept()

    def _clear(self):
        self.selected_shortcut = ""  # Empty string for None
        self.accept()
