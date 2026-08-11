from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SimpleCardWidget,
    Slider,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
    TransparentToolButton,
)


class ControlCard(SimpleCardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setBorderRadius(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 16)
        self.layout.setSpacing(12)
        self.layout.addWidget(StrongBodyLabel(title, self))


class WindowsControlsWidget(QWidget):
    refresh_requested = Signal()
    action_requested = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("windowsControlsPage")
        self._quick_columns = 0
        self._session_columns = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(SubtitleLabel("Windows 控制", self))
        header.addStretch(1)
        refresh = TransparentToolButton(FluentIcon.SYNC, self)
        refresh.setToolTip("刷新系统状态")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh)
        outer.addLayout(header)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.enableTransparentBackground()
        self.content = QWidget(self.scroll)
        self.content.setObjectName("windowsControlsContent")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 6, 0)
        content_layout.setSpacing(10)

        audio = ControlCard("音频", self.content)
        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        audio_row.addStretch(1)
        for icon, tooltip, action in (
            (FluentIcon.DOWN, "降低音量", "volume_down"),
            (FluentIcon.MUTE, "静音或取消静音", "mute"),
            (FluentIcon.VOLUME, "提高音量", "volume_up"),
        ):
            button = ToolButton(icon, audio)
            button.setFixedSize(44, 40)
            button.setToolTip(tooltip)
            button.clicked.connect(
                lambda _=False, name=action: self.action_requested.emit(name, None)
            )
            audio_row.addWidget(button)
        audio_row.addStretch(1)
        audio.layout.addLayout(audio_row)
        content_layout.addWidget(audio)

        display = ControlCard("显示", self.content)
        brightness_heading = QHBoxLayout()
        brightness_heading.addWidget(CaptionLabel("亮度", display))
        brightness_heading.addStretch(1)
        self.brightness_value = StrongBodyLabel("--", display)
        brightness_heading.addWidget(self.brightness_value)
        display.layout.addLayout(brightness_heading)
        self.brightness = Slider(Qt.Orientation.Horizontal, display)
        self.brightness.setRange(0, 100)
        self.brightness.setEnabled(False)
        self.brightness.sliderReleased.connect(
            lambda: self.action_requested.emit("brightness", self.brightness.value())
        )
        self.brightness.valueChanged.connect(
            lambda value: self.brightness_value.setText(f"{value}%")
        )
        display.layout.addWidget(self.brightness)
        content_layout.addWidget(display)

        settings = ControlCard("快捷设置", self.content)
        self.quick_grid = QGridLayout()
        self.quick_grid.setHorizontalSpacing(8)
        self.quick_grid.setVerticalSpacing(8)
        entries = (
            ("显示", FluentIcon.FULL_SCREEN, "display"),
            ("声音", FluentIcon.SPEAKERS, "sound"),
            ("网络", FluentIcon.WIFI, "network"),
            ("蓝牙", FluentIcon.BLUETOOTH, "bluetooth"),
            ("夜间模式", FluentIcon.BRIGHTNESS, "night_light"),
            ("电源", FluentIcon.POWER_BUTTON, "power"),
        )
        self.quick_buttons = []
        for text, icon, action in entries:
            button = PushButton(text, settings, icon)
            button.setMinimumHeight(42)
            button.clicked.connect(
                lambda _=False, name=action: self.action_requested.emit(name, None)
            )
            self.quick_buttons.append(button)
        settings.layout.addLayout(self.quick_grid)
        content_layout.addWidget(settings)

        power = ControlCard("电源计划", self.content)
        power_row = QHBoxLayout()
        power_row.setSpacing(8)
        self.power_plans = ComboBox(power)
        self.power_plans.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.apply_plan = PrimaryPushButton(FluentIcon.ACCEPT, "应用", power)
        self.apply_plan.setEnabled(False)
        self.apply_plan.clicked.connect(self._apply_power_plan)
        power_row.addWidget(self.power_plans, 1)
        power_row.addWidget(self.apply_plan)
        power.layout.addLayout(power_row)
        content_layout.addWidget(power)

        session = ControlCard("会话", self.content)
        self.session_grid = QGridLayout()
        self.session_grid.setHorizontalSpacing(8)
        self.session_grid.setVerticalSpacing(8)
        self.session_buttons = []
        for text, icon, action in (
            ("锁定", FluentIcon.HIDE, "lock"),
            ("睡眠", FluentIcon.PAUSE, "sleep"),
            ("重启", FluentIcon.SYNC, "restart"),
            ("关机", FluentIcon.POWER_BUTTON, "shutdown"),
        ):
            button = PushButton(text, session, icon)
            button.setMinimumHeight(42)
            button.clicked.connect(
                lambda _=False, name=action: self._confirm_session_action(name)
            )
            self.session_buttons.append(button)
        session.layout.addLayout(self.session_grid)
        content_layout.addWidget(session)
        content_layout.addStretch(1)

        self._arrange_grid(self.quick_grid, self.quick_buttons, 2, "quick")
        self._arrange_grid(self.session_grid, self.session_buttons, 2, "session")
        self.scroll.setWidget(self.content)
        outer.addWidget(self.scroll, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_requested.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        width = event.size().width()
        self._arrange_grid(
            self.quick_grid,
            self.quick_buttons,
            3 if width >= 760 else 2,
            "quick",
        )
        self._arrange_grid(
            self.session_grid,
            self.session_buttons,
            4 if width >= 760 else 2,
            "session",
        )

    def apply_snapshot(self, snapshot):
        brightness = snapshot.get("brightness")
        self.brightness.setEnabled(brightness is not None)
        if brightness is not None:
            self.brightness.setValue(int(brightness))
            self.brightness.setToolTip(f"当前亮度 {int(brightness)}%")
        else:
            self.brightness_value.setText("不可用")
            self.brightness.setToolTip("当前显示设备不支持亮度控制")

        self.power_plans.clear()
        for plan in snapshot.get("power_plans", []):
            self.power_plans.addItem(plan["name"], userData=plan["guid"])
            if plan.get("active"):
                self.power_plans.setCurrentIndex(self.power_plans.count() - 1)
        self.apply_plan.setEnabled(self.power_plans.count() > 0)
        if snapshot.get("errors"):
            self.show_error("；".join(snapshot["errors"]))

    def show_error(self, message):
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.error("操作失败", str(message), parent=self, position=InfoBarPosition.TOP)

    def show_completed(self, action):
        if action in {"volume_up", "volume_down", "mute", "lock"}:
            return
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.success("已执行", "系统操作已提交。", parent=self, position=InfoBarPosition.TOP)

    def _arrange_grid(self, layout, widgets, columns, name):
        attribute = "_quick_columns" if name == "quick" else "_session_columns"
        if getattr(self, attribute) == columns:
            return
        while layout.count():
            layout.takeAt(0)
        for index, widget in enumerate(widgets):
            layout.addWidget(widget, index // columns, index % columns)
        for column in range(columns):
            layout.setColumnStretch(column, 1)
        setattr(self, attribute, columns)

    def _apply_power_plan(self):
        guid = self.power_plans.currentData()
        if guid:
            self.action_requested.emit("power_plan", guid)

    def _confirm_session_action(self, action):
        labels = {"lock": "锁定", "sleep": "睡眠", "restart": "重启", "shutdown": "关机"}
        if action == "lock":
            self.action_requested.emit(action, None)
            return
        if MessageBox("确认系统操作", f"确定要{labels[action]}当前电脑？", self.window()).exec():
            self.action_requested.emit(action, None)


__all__ = ["WindowsControlsWidget"]
