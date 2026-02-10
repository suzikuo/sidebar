from PySide6.QtCore import Qt, QTime, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    LineEdit,
    StrongBodyLabel,
    SwitchButton,
)


class ClockWidget(StrongBodyLabel):
    """
    A widget that displays the current time.
    Supports customization of format and color via plugin state.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._format = "HH:mm"
        self._color = "white"
        self._orientation = "vertical"

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)

        self.update_time()

    def set_orientation(self, orientation: str):
        self._orientation = orientation
        self.update_time()

    def set_config(self, time_format: str, color: str):
        self._format = time_format
        self._color = color
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.update_time()

    def update_time(self):
        current_time = QTime.currentTime().toString(self._format)
        if self._orientation == "top":
            # Horizontal bar: show HH:mm normally
            self.setText(current_time)
        else:
            # Vertical bar: stack characters
            # For formats like HH:mm:ss, stacking might be ugly,
            # but we follow the original logic of VerticalTimeWidget.
            # VerticalTimeWidget used join() on chars.
            vertical_text = "\n".join(list(current_time))
            self.setText(vertical_text)


class TimeSettingsWidget(QWidget):
    """
    Settings UI for the Time plugin.
    """

    config_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title = BodyLabel("Time Plugin Settings", self)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        # Enable/Disable
        self.enable_card = CardWidget(self)
        enable_layout = QHBoxLayout(self.enable_card)
        enable_layout.addWidget(BodyLabel("Show Clock", self.enable_card))
        enable_layout.addStretch(1)
        self.enable_switch = SwitchButton(self.enable_card)
        self.enable_switch.checkedChanged.connect(self._on_changed)
        enable_layout.addWidget(self.enable_switch)
        layout.addWidget(self.enable_card)

        # Format
        self.format_card = CardWidget(self)
        format_layout = QHBoxLayout(self.format_card)
        format_layout.addWidget(BodyLabel("Time Format", self.format_card))
        format_layout.addStretch(1)
        self.format_input = LineEdit(self.format_card)
        self.format_input.setPlaceholderText("e.g. HH:mm or HH:mm:ss")
        self.format_input.textChanged.connect(self._on_changed)
        format_layout.addWidget(self.format_input)
        layout.addWidget(self.format_card)

        # Color
        self.color_card = CardWidget(self)
        color_layout = QHBoxLayout(self.color_card)
        color_layout.addWidget(BodyLabel("Font Color", self.color_card))
        color_layout.addStretch(1)
        # Using a QSS-styled label or a simple color input for now
        # because ColorPickerButton might be too complex for a quick refactor
        # or require more context. Let's use a LineEdit for color hex initially.
        self.color_input = LineEdit(self.color_card)
        self.color_input.setPlaceholderText("e.g. white or #FF0000")
        self.color_input.textChanged.connect(self._on_changed)
        color_layout.addWidget(self.color_input)
        layout.addWidget(self.color_card)

        layout.addStretch(1)

    def set_config(self, config: dict):
        self.enable_switch.blockSignals(True)
        self.format_input.blockSignals(True)
        self.color_input.blockSignals(True)

        self.enable_switch.setChecked(config.get("enabled", True))
        self.format_input.setText(config.get("format", "HH:mm"))
        self.color_input.setText(config.get("color", "white"))

        self.enable_switch.blockSignals(False)
        self.format_input.blockSignals(False)
        self.color_input.blockSignals(False)

    def _on_changed(self):
        config = {
            "enabled": self.enable_switch.isChecked(),
            "format": self.format_input.text(),
            "color": self.color_input.text(),
        }
        self.config_changed.emit(config)
