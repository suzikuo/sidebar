import datetime

from PySide6.QtCore import Qt, QTime, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ColorPickerButton,
    LineEdit,
    Pivot,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SwitchButton,
    TimePicker,
)

from plugins.time.logic import DAY_NAMES_CN, format_days


# ────────────────────────────────────────────────────────────────
# Clock Widget (sidebar display)
# ────────────────────────────────────────────────────────────────
class ClockWidget(StrongBodyLabel):
    """
    A widget that displays the current time.
    When an alarm is <= 5 minutes away, switches to countdown mode.
    Click opens the alarm detail page.
    """

    clicked = Signal()

    COUNTDOWN_THRESHOLD = 5 * 60  # 5 minutes in seconds

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self._format = "HH:mm"
        self._color = "white"
        self._orientation = "vertical"
        self._alarm_manager = None
        self._in_countdown = False  # Whether currently showing countdown
        self._tick_count = 0
        self._tick_count = 0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time)
        self.timer.start(1000)

        self.setCursor(Qt.PointingHandCursor)
        self.update_time()

    def set_alarm_manager(self, manager):
        """Connect the alarm manager so we can query next alarm info."""
        self._alarm_manager = manager

    def set_orientation(self, orientation: str):
        self._orientation = orientation
        self.update_time()

    def set_config(self, time_format: str, color: str):
        self._format = time_format
        self._color = color
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.update_time()

    def mousePressEvent(self, e):
        """Emit clicked signal."""
        self.clicked.emit()
        super().mousePressEvent(e)

    def update_time(self):
        self._tick_count += 1
        # Check if alarm is approaching
        alarm_info = None
        if self._alarm_manager:
            alarm_info = self._alarm_manager.get_next_alarm_info()

        if alarm_info and alarm_info["remaining_seconds"] <= self.COUNTDOWN_THRESHOLD:
            self._in_countdown = True

            if self._orientation == "top":
                # Horizontal: Show combined
                self._render_combined(alarm_info)
            else:
                # Vertical: Alternate every 5s
                # 0-4: Clock, 5-9: Countdown
                if (self._tick_count % 10) < 5:
                    self._render_clock()
                else:
                    self._render_countdown(alarm_info)
        else:
            self._in_countdown = False
            self._render_clock()

    def _render_clock(self):
        """Normal clock display."""
        self.setStyleSheet(f"color: {self._color}; background: transparent;")
        current_time = QTime.currentTime().toString(self._format)
        if self._orientation == "top":
            self.setText(current_time)
        else:
            self.setText("\n".join(list(current_time)))

    def _render_countdown(self, info: dict):
        """Countdown display when alarm is near (Vertical Only in this logic branch)."""
        remaining = max(0, int(info["remaining_seconds"]))
        mins = remaining // 60
        secs = remaining % 60
        countdown_str = f"{mins}:{secs:02d}"

        # Highlight color for countdown
        self.setStyleSheet("color: #FFB900; background: transparent;")

        # Vertical: stack characters
        # Vertical: stack characters
        lines = ["⏱️", countdown_str]
        self.setText("\n".join(lines))

    def _render_combined(self, info: dict):
        """Horizontal combined display: Time ... Countdown"""
        current_time = QTime.currentTime().toString(self._format)

        # remaining = max(0, int(info["remaining_seconds"]))
        countdown_str = "⏱️"

        self.setStyleSheet("color: #FFB900; background: transparent;")

        text = f"{countdown_str}{current_time}"

        self.setText(text)


# ────────────────────────────────────────────────────────────────
# Alarm Card (list item)
# ────────────────────────────────────────────────────────────────
class AlarmCard(CardWidget):
    """
    A card representing a single alarm, styled like mobile alarm apps.
    Shows large time, repeat info, label, and an on/off toggle switch.
    """

    toggled = Signal(bool)
    edit_requested = Signal()

    def __init__(self, alarm_data: dict, parent=None):
        super().__init__(parent)
        self.alarm_data = alarm_data
        self.setFixedHeight(80)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 12, 20, 12)
        main_layout.setSpacing(12)

        # ── Left: Time + Info ──
        left = QVBoxLayout()
        left.setSpacing(2)

        # Large time text
        hour = alarm_data.get("hour", 0)
        minute = alarm_data.get("minute", 0)
        time_str = f"{hour:02d}:{minute:02d}"

        self.time_label = StrongBodyLabel(time_str, self)
        time_font = QFont()
        time_font.setPointSize(24)
        time_font.setWeight(QFont.Weight.DemiBold)
        self.time_label.setFont(time_font)

        # Subtitle: repeat info | label
        days = alarm_data.get("days", [])
        label = alarm_data.get("label", "")
        subtitle_parts = [format_days(days)]
        if label:
            subtitle_parts.append(label)
        subtitle_text = " | ".join(subtitle_parts)

        self.subtitle_label = BodyLabel(subtitle_text, self)
        self.subtitle_label.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 12px;"
        )

        left.addWidget(self.time_label)
        left.addWidget(self.subtitle_label)

        # ── Right: Switch ──
        self.switch = SwitchButton(self)
        self.switch.setChecked(alarm_data.get("enabled", True))
        self.switch.checkedChanged.connect(self.toggled)

        main_layout.addLayout(left)
        main_layout.addStretch(1)
        main_layout.addWidget(self.switch)

        self.setCursor(Qt.PointingHandCursor)

        # Dim if disabled
        if not alarm_data.get("enabled", True):
            self.time_label.setStyleSheet(
                "color: rgba(255,255,255,0.35); background: transparent;"
            )
            self.subtitle_label.setStyleSheet(
                "color: rgba(255,255,255,0.2); background: transparent;"
            )
        else:
            self.time_label.setStyleSheet("background: transparent;")
            self.subtitle_label.setStyleSheet(
                "color: rgba(255,255,255,0.5); background: transparent;"
            )

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.edit_requested.emit()


# ────────────────────────────────────────────────────────────────
# Day-of-Week Toggle Button
# ────────────────────────────────────────────────────────────────
class DayToggleButton(PushButton):
    """A small toggleable button for a single day of the week."""

    def __init__(self, day_index: int = 0, parent=None):
        super().__init__(parent)
        self.setText(DAY_NAMES_CN[day_index])
        self.day_index = day_index
        self._selected = False
        self.setFixedSize(42, 36)
        self.setCheckable(True)
        self.clicked.connect(self._on_click)
        self._apply_style()

    def setSelected(self, selected: bool):
        self._selected = selected
        self.setChecked(selected)
        self._apply_style()

    def isSelected(self) -> bool:
        return self._selected

    def _on_click(self):
        self._selected = not self._selected
        self._apply_style()

    def _apply_style(self):
        if self._selected:
            self.setStyleSheet(
                "QPushButton { background: #0078d4; color: white; border-radius: 6px; "
                "font-size: 12px; border: none; }"
            )
        else:
            self.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.5); "
                "border-radius: 6px; font-size: 12px; border: none; }"
            )


# ────────────────────────────────────────────────────────────────
# Alarm Edit Dialog
# ────────────────────────────────────────────────────────────────
class AlarmEditDialog(QDialog):
    """
    Dialog to add or edit an alarm.
    Uses TimePicker for hour/minute and day-of-week toggles for recurrence.
    """

    def __init__(self, alarm_data=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑闹钟" if alarm_data else "添加闹钟")
        self.alarm_data = alarm_data or {}
        self.resize(360, 380)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # ── Time Picker ──
        layout.addWidget(BodyLabel("时间", self))
        self.time_picker = TimePicker(self)
        hour = self.alarm_data.get("hour", datetime.datetime.now().hour)
        minute = self.alarm_data.get(
            "minute", (datetime.datetime.now().minute + 1) % 60
        )
        self.time_picker.setTime(QTime(hour, minute))
        layout.addWidget(self.time_picker)

        layout.addSpacing(4)

        # ── Day-of-week toggles ──
        repeat_header = QHBoxLayout()
        repeat_header.addWidget(BodyLabel("重复", self))
        repeat_header.addStretch(1)
        self.everyday_btn = PushButton("每天", self)
        self.everyday_btn.setFixedWidth(60)
        self.everyday_btn.clicked.connect(self._select_everyday)
        repeat_header.addWidget(self.everyday_btn)
        layout.addLayout(repeat_header)

        days_layout = QHBoxLayout()
        days_layout.setSpacing(6)
        self.day_buttons: list[DayToggleButton] = []

        selected_days = self.alarm_data.get("days", [])
        for i in range(7):
            btn = DayToggleButton(i, self)
            if i in selected_days:
                btn.setSelected(True)
            self.day_buttons.append(btn)
            days_layout.addWidget(btn)
        layout.addLayout(days_layout)

        layout.addSpacing(4)

        # ── Label input ──
        layout.addWidget(BodyLabel("备注", self))
        self.label_input = LineEdit(self)
        self.label_input.setPlaceholderText("输入内容")
        self.label_input.setText(self.alarm_data.get("label", ""))
        layout.addWidget(self.label_input)

        layout.addStretch(1)

        # ── Buttons ──
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        if alarm_data:
            delete_btn = buttons.addButton("删除", QDialogButtonBox.DestructiveRole)
            delete_btn.clicked.connect(lambda: self.done(2))

        layout.addWidget(buttons)

    def _select_everyday(self):
        """Toggle all day buttons."""
        # If all are already selected, maybe deselect all?
        # But usually "Every Day" means "Ensure all are on".
        # Let's check if all are already on.
        all_on = all(btn.isSelected() for btn in self.day_buttons)
        target = not all_on
        for btn in self.day_buttons:
            btn.setSelected(target)

    def get_data(self) -> dict:
        t = self.time_picker.time
        days = [btn.day_index for btn in self.day_buttons if btn.isSelected()]
        return {
            "hour": t.hour() if t else 0,
            "minute": t.minute() if t else 0,
            "days": days,
            "label": self.label_input.text(),
            "enabled": self.alarm_data.get("enabled", True),
        }


# ────────────────────────────────────────────────────────────────
# Alarm List Widget
# ────────────────────────────────────────────────────────────────
class AlarmListWidget(QWidget):
    """Widget to display a scrollable list of alarm cards."""

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.manager.alarms_changed.connect(self._refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header with Add Button
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 10)

        title = BodyLabel("闹钟", header)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")

        add_btn = PrimaryPushButton("添加闹钟", header)
        add_btn.clicked.connect(self._add_alarm)

        header_layout.addWidget(title)
        header_layout.addStretch(1)
        header_layout.addWidget(add_btn)

        layout.addWidget(header)

        # Scroll Area
        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.list_layout = QVBoxLayout(self.scroll_content)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.list_layout.setSpacing(8)

        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll)

        self._refresh(self.manager.get_alarms())

    def _refresh(self, alarms):
        # Clear existing
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for alarm in alarms:
            card = AlarmCard(alarm, self.scroll_content)
            card.toggled.connect(
                lambda checked, aid=alarm["id"]: self.manager.update_alarm(
                    aid, {"enabled": checked}
                )
            )
            card.edit_requested.connect(lambda a=alarm: self._edit_alarm(a))
            self.list_layout.addWidget(card)

    def _add_alarm(self):
        dialog = AlarmEditDialog(parent=self.window())
        if dialog.exec():
            data = dialog.get_data()
            self.manager.add_alarm(data)

    def _edit_alarm(self, alarm):
        dialog = AlarmEditDialog(alarm, parent=self.window())
        result = dialog.exec()
        if result == 1:  # Accepted
            data = dialog.get_data()
            self.manager.update_alarm(alarm["id"], data)
        elif result == 2:  # Delete
            self.manager.remove_alarm(alarm["id"])


# ────────────────────────────────────────────────────────────────
# Time Settings Widget (tabbed: Clock + Alarms)
# ────────────────────────────────────────────────────────────────
class TimeSettingsWidget(QWidget):
    """
    Settings UI for the Time plugin.
    Supports both Clock settings and Alarm list via tabs.
    """

    config_changed = Signal(dict)

    def __init__(self, alarm_manager, parent=None):
        super().__init__(parent)
        self.alarm_manager = alarm_manager
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Tabs (Pivot)
        self.pivot = Pivot(self)
        self.pivot.addItem(routeKey="clock", text="时钟")
        self.pivot.addItem(routeKey="alarms", text="闹钟")
        self.pivot.setCurrentItem("clock")
        self.pivot.currentItemChanged.connect(
            lambda k: self.stacked_widget.setCurrentWidget(self.page_map[k])
        )
        layout.addWidget(self.pivot)

        # Stacked Widget
        self.stacked_widget = QStackedWidget(self)

        # Page 1: Clock Settings
        self.clock_settings_page = QWidget()
        self._init_clock_settings(self.clock_settings_page)

        # Page 2: Alarms
        self.alarms_page = AlarmListWidget(self.alarm_manager)

        self.stacked_widget.addWidget(self.clock_settings_page)
        self.stacked_widget.addWidget(self.alarms_page)

        self.page_map = {"clock": self.clock_settings_page, "alarms": self.alarms_page}

        layout.addWidget(self.stacked_widget)

    def _init_clock_settings(self, parent):
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(15)

        # Enable/Disable
        self.enable_card = CardWidget(parent)
        enable_layout = QHBoxLayout(self.enable_card)
        enable_layout.addWidget(BodyLabel("显示时钟", self.enable_card))
        enable_layout.addStretch(1)
        self.enable_switch = SwitchButton(self.enable_card)
        self.enable_switch.checkedChanged.connect(self._on_changed)
        enable_layout.addWidget(self.enable_switch)
        layout.addWidget(self.enable_card)

        # Format
        self.format_card = CardWidget(parent)
        format_layout = QHBoxLayout(self.format_card)
        format_layout.addWidget(BodyLabel("时间格式", self.format_card))
        format_layout.addStretch(1)
        self.format_input = LineEdit(self.format_card)
        self.format_input.setPlaceholderText("e.g. HH:mm or HH:mm:ss")
        self.format_input.textChanged.connect(self._on_changed)
        format_layout.addWidget(self.format_input)
        layout.addWidget(self.format_card)

        # Color
        self.color_card = CardWidget(parent)
        color_layout = QHBoxLayout(self.color_card)
        color_layout.addWidget(BodyLabel("字体颜色", self.color_card))
        color_layout.addStretch(1)

        self.color_picker = ColorPickerButton(
            QColor("white"), "Select Color", self.color_card
        )
        self.color_picker.colorChanged.connect(self._on_changed)
        color_layout.addWidget(self.color_picker)
        layout.addWidget(self.color_card)

        layout.addStretch(1)

    def set_config(self, config: dict):
        self.enable_switch.blockSignals(True)
        self.format_input.blockSignals(True)
        self.color_picker.blockSignals(True)

        self.enable_switch.setChecked(config.get("enabled", True))
        self.format_input.setText(config.get("format", "HH:mm"))
        self.color_picker.setColor(QColor(config.get("color", "white")))

        self.enable_switch.blockSignals(False)
        self.format_input.blockSignals(False)
        self.color_picker.blockSignals(False)

    def _on_changed(self):
        config = {
            "enabled": self.enable_switch.isChecked(),
            "format": self.format_input.text(),
            "color": self.color_picker.color.name(),
        }
        self.config_changed.emit(config)
