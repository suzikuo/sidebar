"""Native PySide6 widgets for live traffic and v2rayN settings."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ColorPickerButton,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    Slider,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
)

from ui.components.base_widget import BScrollArea

from .service import DEFAULT_CONFIG, NetworkSnapshot, normalize_config


def format_rate(value: float | None) -> str:
    if value is None:
        return "--"
    value = max(0.0, float(value))
    units = ("B/s", "KB/s", "MB/s", "GB/s")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024.0 or candidate == units[-1]:
            break
        value /= 1024.0
    precision = 0 if unit == "B/s" else 1
    return f"{value:.{precision}f} {unit}"


class TrafficMetricCard(CardWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(185)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(StrongBodyLabel(title, self))
        self.upload_label = BodyLabel("↑ 上传  --", self)
        self.download_label = BodyLabel("↓ 下载  --", self)
        layout.addWidget(self.upload_label)
        layout.addWidget(self.download_label)

    def set_rates(self, rates):
        upload = format_rate(
            None if rates is None else rates.upload_bytes_per_second
        )
        download = format_rate(
            None if rates is None else rates.download_bytes_per_second
        )
        self.upload_label.setText(f"↑ 上传  {upload}")
        self.download_label.setText(f"↓ 下载  {download}")


class NetworkMonitorWidget(QWidget):
    config_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = BScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll = scroll
        content = QWidget(scroll)
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        layout.addWidget(SubtitleLabel("网络监控", content))
        self.status_label = BodyLabel("等待首次采样", content)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        metrics = QVBoxLayout()
        metrics.setSpacing(12)
        self.system_card = TrafficMetricCard("总网络", content)
        self.proxy_card = TrafficMetricCard("v2rayN 代理", content)
        self.direct_card = TrafficMetricCard("直连（估算）", content)
        metrics.addWidget(self.system_card)
        metrics.addWidget(self.proxy_card)
        metrics.addWidget(self.direct_card)
        layout.addLayout(metrics)

        layout.addWidget(SubtitleLabel("悬浮窗", content))
        appearance = CardWidget(content)
        appearance_form = QFormLayout(appearance)
        appearance_form.setContentsMargins(18, 16, 18, 16)
        appearance_form.setHorizontalSpacing(18)
        appearance_form.setVerticalSpacing(12)
        appearance_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        appearance_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        appearance_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.floating_switch = SwitchButton(appearance)
        appearance_form.addRow("显示桌面悬浮窗", self.floating_switch)

        self.floating_lock_switch = SwitchButton(appearance)
        appearance_form.addRow("锁定悬浮窗（鼠标穿透）", self.floating_lock_switch)

        self.background_color_picker = ColorPickerButton(
            QColor(DEFAULT_CONFIG["floating_background_color"]),
            "选择悬浮窗背景颜色",
            appearance,
        )
        appearance_form.addRow("背景颜色", self.background_color_picker)

        opacity_control = QWidget(appearance)
        opacity_layout = QHBoxLayout(opacity_control)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(10)
        self.background_opacity_slider = Slider(
            Qt.Orientation.Horizontal,
            opacity_control,
        )
        self.background_opacity_slider.setRange(0, 100)
        self.background_opacity_value = BodyLabel("0%", opacity_control)
        self.background_opacity_value.setFixedWidth(44)
        self.background_opacity_value.setAlignment(Qt.AlignmentFlag.AlignRight)
        opacity_layout.addWidget(self.background_opacity_slider, 1)
        opacity_layout.addWidget(self.background_opacity_value)
        appearance_form.addRow("背景不透明度", opacity_control)

        self.font_color_picker = ColorPickerButton(
            QColor(DEFAULT_CONFIG["floating_font_color"]),
            "选择悬浮窗字体颜色",
            appearance,
        )
        appearance_form.addRow("字体颜色", self.font_color_picker)
        layout.addWidget(appearance)

        layout.addWidget(SubtitleLabel("v2rayN 指标", content))
        settings = CardWidget(content)
        form = QFormLayout(settings)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self.enabled_switch = SwitchButton(settings)
        form.addRow("启用代理统计", self.enabled_switch)

        self.host_input = LineEdit(settings)
        self.host_input.setPlaceholderText("127.0.0.1")
        form.addRow("指标地址", self.host_input)

        self.port_input = SpinBox(settings)
        self.port_input.setRange(1, 65535)
        form.addRow("指标端口", self.port_input)

        self.refresh_input = SpinBox(settings)
        self.refresh_input.setRange(500, 10000)
        self.refresh_input.setSuffix(" ms")
        form.addRow("刷新间隔", self.refresh_input)

        self.timeout_input = SpinBox(settings)
        self.timeout_input.setRange(100, 10000)
        self.timeout_input.setSuffix(" ms")
        form.addRow("查询超时", self.timeout_input)
        layout.addWidget(settings)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_button = PrimaryPushButton(
            FluentIcon.SAVE,
            "保存配置",
            content,
        )
        self.save_button.clicked.connect(self._save)
        self.floating_switch.checkedChanged.connect(self._save)
        self.floating_lock_switch.checkedChanged.connect(self._save)
        self.background_color_picker.colorChanged.connect(self._save)
        self.font_color_picker.colorChanged.connect(self._save)
        self.background_opacity_slider.valueChanged.connect(
            self._update_opacity_value
        )
        self.background_opacity_slider.sliderReleased.connect(self._save)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        layout.addStretch(1)

        self.set_config(DEFAULT_CONFIG)

    def set_config(self, value):
        config = normalize_config(value)
        controls = (
            self.enabled_switch,
            self.floating_switch,
            self.floating_lock_switch,
            self.background_color_picker,
            self.background_opacity_slider,
            self.font_color_picker,
            self.host_input,
            self.port_input,
            self.refresh_input,
            self.timeout_input,
        )
        for control in controls:
            control.blockSignals(True)
        self.enabled_switch.setChecked(config["v2rayn_enabled"])
        self.floating_switch.setChecked(config["floating_enabled"])
        self.floating_lock_switch.setChecked(config["floating_locked"])
        self.background_color_picker.setColor(
            QColor(config["floating_background_color"])
        )
        self.background_opacity_slider.setValue(
            config["floating_background_opacity"]
        )
        self._update_opacity_value(config["floating_background_opacity"])
        self.font_color_picker.setColor(QColor(config["floating_font_color"]))
        self.host_input.setText(config["v2rayn_host"])
        self.port_input.setValue(config["v2rayn_metrics_port"])
        self.refresh_input.setValue(config["refresh_interval_ms"])
        self.timeout_input.setValue(config["timeout_ms"])
        for control in controls:
            control.blockSignals(False)

    def set_snapshot(self, snapshot: NetworkSnapshot):
        self.system_card.set_rates(snapshot.system)
        self.proxy_card.set_rates(snapshot.proxy)
        self.direct_card.set_rates(snapshot.direct)
        if snapshot.system_error:
            self.status_label.setText(f"系统网络读取失败：{snapshot.system_error}")
        elif snapshot.proxy_error:
            self.status_label.setText(f"V2Ray 未连接：{snapshot.proxy_error}")
        elif not snapshot.v2rayn_enabled:
            self.status_label.setText("系统网络正常；v2rayN 代理统计未启用")
        elif snapshot.v2rayn_connected:
            self.status_label.setText("系统网络与 v2rayN Xray Metrics 均已连接")
        else:
            self.status_label.setText("等待 v2rayN Xray Metrics 数据")

    def show_config_error(self, message):
        InfoBar.error(
            "配置无效",
            str(message),
            duration=5000,
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )

    def show_config_saved(self):
        InfoBar.success(
            "已保存",
            "网络监控配置已应用。",
            duration=2000,
            parent=self.window(),
            position=InfoBarPosition.TOP,
        )

    def _save(self, *_args):
        self.config_changed.emit(
            {
                "v2rayn_enabled": self.enabled_switch.isChecked(),
                "floating_enabled": self.floating_switch.isChecked(),
                "floating_locked": self.floating_lock_switch.isChecked(),
                "floating_background_color": self.background_color_picker.color.name(),
                "floating_background_opacity": self.background_opacity_slider.value(),
                "floating_font_color": self.font_color_picker.color.name(),
                "v2rayn_host": self.host_input.text().strip(),
                "v2rayn_metrics_port": self.port_input.value(),
                "refresh_interval_ms": self.refresh_input.value(),
                "timeout_ms": self.timeout_input.value(),
            }
        )

    def _update_opacity_value(self, value):
        self.background_opacity_value.setText(f"{int(value)}%")


__all__ = [
    "NetworkMonitorWidget",
    "TrafficMetricCard",
    "format_rate",
]
