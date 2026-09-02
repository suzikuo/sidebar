"""Native PySide6 live, history, and settings views for network traffic."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ColorPickerButton,
    ComboBox,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PrimaryPushButton,
    Pivot,
    Slider,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
)

from core.ui_kernel.components.base_widget import BScrollArea

from .service import DEFAULT_CONFIG, NetworkSnapshot, normalize_config


UPLOAD_COLOR = QColor("#F5A623")
DOWNLOAD_COLOR = QColor("#35B86B")
GRID_COLOR = QColor(128, 128, 128, 50)
APPLICATION_IDLE_RETENTION_SECONDS = 5.0


def format_rate(value: float | None) -> str:
    if value is None:
        return "--"
    return f"{_format_size(value)}/s"


def format_bytes(value: int | float | None) -> str:
    if value is None:
        return "--"
    return _format_size(value)


def _format_size(value) -> str:
    value = max(0.0, float(value))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if value < 1024.0 or candidate == units[-1]:
            break
        value /= 1024.0
    precision = 0 if unit == "B" else 1
    return f"{value:.{precision}f} {unit}"


class TrafficMetricCard(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.title_label = StrongBodyLabel(title, self)
        self.title_label.setMinimumWidth(48)
        layout.addWidget(self.title_label)
        self.download_label = BodyLabel("↓  --", self)
        self.download_label.setStyleSheet(f"color: {DOWNLOAD_COLOR.name()};")
        self.download_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.download_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.upload_label = BodyLabel("↑  --", self)
        self.upload_label.setStyleSheet(f"color: {UPLOAD_COLOR.name()};")
        self.upload_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.upload_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.download_label, 1)
        layout.addWidget(self.upload_label, 1)

    def set_rates(self, rates):
        upload = format_rate(None if rates is None else rates.upload_bytes_per_second)
        download = format_rate(
            None if rates is None else rates.download_bytes_per_second
        )
        self.upload_label.setText(f"↑  {upload}")
        self.download_label.setText(f"↓  {download}")
        self.upload_label.setToolTip(f"上传 {upload}")
        self.download_label.setToolTip(f"下载 {download}")


class TrafficTrendChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []
        self.setMinimumHeight(220)

    def set_points(self, points):
        self._points = list(points or ())
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = QRectF(54, 14, max(1, self.width() - 70), max(1, self.height() - 48))
        text_color = self.palette().text().color()
        painter.setPen(QPen(GRID_COLOR, 1))
        for index in range(5):
            y = plot.top() + plot.height() * index / 4
            painter.drawLine(plot.left(), y, plot.right(), y)

        if not self._points:
            painter.setPen(text_color)
            painter.drawText(plot, Qt.AlignmentFlag.AlignCenter, "暂无历史流量")
            return

        maximum = max(
            1,
            max(
                max(int(point.get("uploadBytes", 0)), int(point.get("downloadBytes", 0)))
                for point in self._points
            ),
        )
        painter.setPen(text_color)
        painter.drawText(
            QRectF(0, plot.top() - 6, 50, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            format_bytes(maximum),
        )
        painter.drawText(
            QRectF(0, plot.bottom() - 9, 50, 18),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            "0 B",
        )
        self._draw_series(painter, plot, maximum, "uploadBytes", UPLOAD_COLOR)
        self._draw_series(painter, plot, maximum, "downloadBytes", DOWNLOAD_COLOR)

        first = datetime.fromtimestamp(int(self._points[0]["timestamp"]))
        last = datetime.fromtimestamp(int(self._points[-1]["timestamp"]))
        painter.setPen(text_color)
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 8, plot.width() / 2, 18),
            Qt.AlignmentFlag.AlignLeft,
            first.strftime("%m-%d %H:%M"),
        )
        painter.drawText(
            QRectF(plot.center().x(), plot.bottom() + 8, plot.width() / 2, 18),
            Qt.AlignmentFlag.AlignRight,
            last.strftime("%m-%d %H:%M"),
        )

    def _draw_series(self, painter, plot, maximum, key, color):
        path = QPainterPath()
        count = len(self._points)
        for index, point in enumerate(self._points):
            x = plot.left() + plot.width() * index / max(1, count - 1)
            value = max(0, int(point.get(key, 0)))
            y = plot.bottom() - plot.height() * value / maximum
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        painter.setPen(QPen(color, 2))
        painter.drawPath(path)


class TrafficRankingChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setMinimumHeight(170)

    def set_items(self, items):
        self._items = list(items or ())[:8]
        self.setMinimumHeight(max(170, 34 + len(self._items) * 32))
        self.updateGeometry()
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_color = self.palette().text().color()
        if not self._items:
            painter.setPen(text_color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无应用排行")
            return
        maximum = max(
            1,
            max(
                int(item.get("uploadBytes", 0)) + int(item.get("downloadBytes", 0))
                for item in self._items
            ),
        )
        label_width = min(160, max(90, int(self.width() * 0.3)))
        metrics = QFontMetrics(self.font())
        bar_left = label_width + 10
        bar_width = max(1, self.width() - bar_left - 78)
        for index, item in enumerate(self._items):
            top = 12 + index * 32
            name = str(item.get("appName") or item.get("appKey") or "未知应用")
            painter.setPen(text_color)
            painter.drawText(
                QRectF(0, top, label_width, 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                metrics.elidedText(name, Qt.TextElideMode.ElideRight, label_width),
            )
            upload = max(0, int(item.get("uploadBytes", 0)))
            download = max(0, int(item.get("downloadBytes", 0)))
            upload_width = bar_width * upload / maximum
            download_width = bar_width * download / maximum
            painter.fillRect(QRectF(bar_left, top + 4, upload_width, 12), UPLOAD_COLOR)
            painter.fillRect(
                QRectF(bar_left + upload_width, top + 4, download_width, 12),
                DOWNLOAD_COLOR,
            )
            painter.drawText(
                QRectF(bar_left + bar_width + 7, top, 68, 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                format_bytes(upload + download),
            )


class NetworkMonitorWidget(QWidget):
    config_changed = Signal(dict)
    history_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 14)
        outer.setSpacing(10)
        self.pivot = Pivot(self)
        self.pivot.addItem(routeKey="live", text="实时流量")
        self.pivot.addItem(routeKey="history", text="历史趋势")
        self.pivot.addItem(routeKey="settings", text="设置")
        self.pivot.setCurrentItem("live")
        outer.addWidget(self.pivot)
        self.stacked_widget = QStackedWidget(self)
        outer.addWidget(self.stacked_widget, 1)

        self.live_page = self._build_live_page()
        self.scroll = self.live_page
        self.history_page = self._build_history_page()
        self.settings_page = self._build_settings_page()
        self._page_map = {
            "live": self.live_page,
            "history": self.history_page,
            "settings": self.settings_page,
        }
        for page in self._page_map.values():
            self.stacked_widget.addWidget(page)
        self.pivot.currentItemChanged.connect(self._switch_page)
        self._current_route = "live"
        self._last_history_request = 0.0
        self._history_loaded = False
        self._sort_scores = {}
        self._application_cache = {}
        self._latest_applications = ()
        self.set_config(DEFAULT_CONFIG)

    def _scroll_page(self):
        scroll = BScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(scroll)
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 8, 2, 10)
        layout.setSpacing(14)
        return scroll, content, layout

    def _build_live_page(self):
        scroll, content, layout = self._scroll_page()
        summary = QWidget(content)
        summary.setObjectName("trafficSummary")
        summary.setStyleSheet(
            "#trafficSummary { border: 1px solid rgba(128,128,128,45); "
            "border-radius: 6px; background: rgba(128,128,128,12); }"
        )
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(16, 12, 16, 12)
        summary_layout.setSpacing(8)
        source_header = QHBoxLayout()
        source_header.addWidget(SubtitleLabel("当前速率", summary))
        source_header.addStretch(1)
        self.source_status_label = BodyLabel("等待数据源", summary)
        self.source_status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.source_status_label.setWordWrap(True)
        source_header.addWidget(self.source_status_label)
        summary_layout.addLayout(source_header)
        self.system_card = TrafficMetricCard("系统", summary)
        self.proxy_card = TrafficMetricCard("V2Ray", summary)
        self.direct_card = TrafficMetricCard("直连", summary)
        for card in (self.system_card, self.proxy_card, self.direct_card):
            summary_layout.addWidget(card)
        layout.addWidget(summary)

        heading = QHBoxLayout()
        heading.addWidget(SubtitleLabel("应用流量", content))
        self.app_status_label = BodyLabel("ETW 正在启动", content)
        self.app_status_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        heading.addWidget(self.app_status_label, 1)
        heading.addWidget(BodyLabel("排序", content))
        self.app_sort_combo = ComboBox(content)
        self.app_sort_combo.addItem("总流量", userData="total")
        self.app_sort_combo.addItem("下载速度", userData="download")
        self.app_sort_combo.addItem("上传速度", userData="upload")
        self.app_sort_combo.addItem("应用名称", userData="name")
        self.app_sort_combo.currentIndexChanged.connect(self._resort_applications)
        heading.addWidget(self.app_sort_combo)
        layout.addLayout(heading)

        self.app_table = QTableWidget(0, 5, content)
        self.app_table.setHorizontalHeaderLabels(
            ["应用", "PID", "连接", "下载速度", "上传速度"]
        )
        self.app_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.app_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.app_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.app_table.setShowGrid(False)
        self.app_table.setStyleSheet(
            "QTableWidget { border: 1px solid rgba(128,128,128,45); "
            "border-radius: 6px; background: transparent; }"
            "QTableWidget::item { padding: 7px; border-bottom: 1px solid rgba(128,128,128,28); }"
        )
        self.app_table.verticalHeader().setVisible(False)
        self.app_table.verticalHeader().setDefaultSectionSize(42)
        self.app_table.setMinimumHeight(360)
        header = self.app_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.app_table)
        layout.addStretch(1)
        return scroll

    def _build_history_page(self):
        scroll, content, layout = self._scroll_page()
        controls = QHBoxLayout()
        controls.addWidget(StrongBodyLabel("来源", content))
        self.history_source = ComboBox(content)
        self.history_source.setMinimumWidth(0)
        self.history_source.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        for label, key in (
            ("系统总流量", "system"),
            ("V2Ray 代理", "v2ray"),
            ("直连估算", "direct"),
            ("应用合计", "application"),
        ):
            self.history_source.addItem(label, userData=key)
        controls.addWidget(self.history_source, 1)
        controls.addWidget(StrongBodyLabel("范围", content))
        self.history_range = ComboBox(content)
        self.history_range.setMinimumWidth(0)
        self.history_range.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed
        )
        for label, key in (
            ("最近 1 分钟", "minute"),
            ("最近 1 小时", "hour"),
            ("今天", "today"),
            ("最近 7 天", "7days"),
            ("最近 30 天", "30days"),
            ("最近 1 年", "365days"),
        ):
            self.history_range.addItem(label, userData=key)
        self.history_range.setCurrentIndex(1)
        controls.addWidget(self.history_range, 1)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.history_status = BodyLabel("切换到历史页后加载数据", content)
        layout.addWidget(self.history_status)
        totals = QHBoxLayout()
        self.history_upload = StrongBodyLabel("上传总量  --", content)
        self.history_download = StrongBodyLabel("下载总量  --", content)
        totals.addWidget(self.history_upload)
        totals.addSpacing(24)
        totals.addWidget(self.history_download)
        totals.addStretch(1)
        layout.addLayout(totals)

        legend = QHBoxLayout()
        legend.addWidget(SubtitleLabel("流量趋势", content))
        legend.addStretch(1)
        upload_legend = BodyLabel("上传", content)
        upload_legend.setStyleSheet(f"color: {UPLOAD_COLOR.name()};")
        download_legend = BodyLabel("下载", content)
        download_legend.setStyleSheet(f"color: {DOWNLOAD_COLOR.name()};")
        legend.addWidget(upload_legend)
        legend.addWidget(download_legend)
        layout.addLayout(legend)
        self.trend_chart = TrafficTrendChart(content)
        layout.addWidget(self.trend_chart)

        layout.addWidget(SubtitleLabel("应用流量排行", content))
        self.ranking_chart = TrafficRankingChart(content)
        layout.addWidget(self.ranking_chart)
        layout.addStretch(1)
        self.history_source.currentIndexChanged.connect(self._request_history)
        self.history_range.currentIndexChanged.connect(self._request_history)
        return scroll

    def _build_settings_page(self):
        scroll, content, layout = self._scroll_page()
        layout.addWidget(SubtitleLabel("网络统计", content))
        network = CardWidget(content)
        network_form = self._form(network)
        self.network_scope_combo = ComboBox(network)
        self.network_scope_combo.addItems(["默认出口网卡", "全部活动网卡"])
        network_form.addRow("统计范围", self.network_scope_combo)
        layout.addWidget(network)

        layout.addWidget(SubtitleLabel("悬浮窗", content))
        appearance = CardWidget(content)
        form = self._form(appearance)
        self.floating_switch = SwitchButton(appearance)
        form.addRow("显示桌面悬浮窗", self.floating_switch)
        self.floating_lock_switch = SwitchButton(appearance)
        form.addRow("锁定悬浮窗（鼠标穿透）", self.floating_lock_switch)
        self.floating_display_combo = ComboBox(appearance)
        self.floating_display_combo.addItems(
            ["代理 + 直连", "系统 + 直连", "系统 + 代理", "系统 + 代理 + 直连"]
        )
        form.addRow("展示内容", self.floating_display_combo)
        self.v2ray_metadata_switch = SwitchButton(appearance)
        form.addRow("显示 V2Ray 节点与延迟", self.v2ray_metadata_switch)
        self.layout_mode_combo = ComboBox(appearance)
        self.layout_mode_combo.addItems(["单行", "双行"])
        form.addRow("布局模式", self.layout_mode_combo)

        scale_control, scale_layout = self._slider_control(appearance)
        self.layout_scale_slider = Slider(Qt.Orientation.Horizontal, scale_control)
        self.layout_scale_slider.setRange(70, 140)
        self.layout_scale_value = BodyLabel("100%", scale_control)
        self.layout_scale_value.setFixedWidth(44)
        scale_layout.addWidget(self.layout_scale_slider, 1)
        scale_layout.addWidget(self.layout_scale_value)
        form.addRow("布局大小", scale_control)
        self.font_size_input = SpinBox(appearance)
        self.font_size_input.setRange(8, 18)
        self.font_size_input.setSuffix(" px")
        form.addRow("字体大小", self.font_size_input)
        self.background_color_picker = ColorPickerButton(
            QColor(DEFAULT_CONFIG["floating_background_color"]),
            "选择悬浮窗背景颜色",
            appearance,
        )
        form.addRow("背景颜色", self.background_color_picker)
        opacity_control, opacity_layout = self._slider_control(appearance)
        self.background_opacity_slider = Slider(
            Qt.Orientation.Horizontal, opacity_control
        )
        self.background_opacity_slider.setRange(0, 100)
        self.background_opacity_value = BodyLabel("0%", opacity_control)
        self.background_opacity_value.setFixedWidth(44)
        opacity_layout.addWidget(self.background_opacity_slider, 1)
        opacity_layout.addWidget(self.background_opacity_value)
        form.addRow("背景不透明度", opacity_control)
        self.font_color_picker = ColorPickerButton(
            QColor(DEFAULT_CONFIG["floating_font_color"]),
            "选择悬浮窗字体颜色",
            appearance,
        )
        form.addRow("字体颜色", self.font_color_picker)
        layout.addWidget(appearance)

        layout.addWidget(SubtitleLabel("应用流量", content))
        applications = CardWidget(content)
        applications_form = self._form(applications)
        self.application_monitor_switch = SwitchButton(applications)
        applications_form.addRow("启用应用级流量", self.application_monitor_switch)
        layout.addWidget(applications)

        layout.addWidget(SubtitleLabel("V2Ray 数据源", content))
        v2ray = CardWidget(content)
        v2ray_form = self._form(v2ray)
        self.enabled_switch = SwitchButton(v2ray)
        v2ray_form.addRow("启用代理流量", self.enabled_switch)
        self.host_input = LineEdit(v2ray)
        self.host_input.setPlaceholderText("127.0.0.1")
        v2ray_form.addRow("Metrics 地址", self.host_input)
        self.port_input = SpinBox(v2ray)
        self.port_input.setRange(1, 65535)
        v2ray_form.addRow("Metrics 端口", self.port_input)
        self.refresh_input = SpinBox(v2ray)
        self.refresh_input.setRange(500, 10000)
        self.refresh_input.setSuffix(" ms")
        v2ray_form.addRow("采样间隔", self.refresh_input)
        self.timeout_input = SpinBox(v2ray)
        self.timeout_input.setRange(100, 10000)
        self.timeout_input.setSuffix(" ms")
        v2ray_form.addRow("查询超时", self.timeout_input)
        layout.addWidget(v2ray)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_button = PrimaryPushButton(FluentIcon.SAVE, "保存配置", content)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        layout.addStretch(1)
        self._connect_settings()
        return scroll

    @staticmethod
    def _form(parent):
        form = QFormLayout(parent)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    @staticmethod
    def _slider_control(parent):
        control = QWidget(parent)
        layout = QHBoxLayout(control)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        return control, layout

    def _connect_settings(self):
        self.save_button.clicked.connect(self._save)
        for control in (
            self.floating_switch,
            self.floating_lock_switch,
            self.v2ray_metadata_switch,
            self.application_monitor_switch,
        ):
            control.checkedChanged.connect(self._save)
        self.floating_display_combo.currentTextChanged.connect(self._save)
        self.network_scope_combo.currentTextChanged.connect(self._save)
        self.layout_mode_combo.currentTextChanged.connect(self._save)
        self.layout_scale_slider.valueChanged.connect(self._update_layout_scale_value)
        self.layout_scale_slider.sliderReleased.connect(self._save)
        self.font_size_input.valueChanged.connect(self._save)
        self.background_color_picker.colorChanged.connect(self._save)
        self.font_color_picker.colorChanged.connect(self._save)
        self.background_opacity_slider.valueChanged.connect(self._update_opacity_value)
        self.background_opacity_slider.sliderReleased.connect(self._save)

    def set_config(self, value):
        config = normalize_config(value)
        controls = (
            self.enabled_switch,
            self.network_scope_combo,
            self.application_monitor_switch,
            self.floating_switch,
            self.floating_lock_switch,
            self.floating_display_combo,
            self.v2ray_metadata_switch,
            self.layout_mode_combo,
            self.layout_scale_slider,
            self.font_size_input,
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
        self.network_scope_combo.setCurrentText(
            "全部活动网卡"
            if config["network_scope"] == "all_active"
            else "默认出口网卡"
        )
        self.application_monitor_switch.setChecked(
            config["application_monitor_enabled"]
        )
        self.floating_switch.setChecked(config["floating_enabled"])
        self.floating_lock_switch.setChecked(config["floating_locked"])
        display_labels = {
            "proxy_direct": "代理 + 直连",
            "system_direct": "系统 + 直连",
            "system_proxy": "系统 + 代理",
            "system_proxy_direct": "系统 + 代理 + 直连",
        }
        self.floating_display_combo.setCurrentText(
            display_labels[config["floating_display_mode"]]
        )
        self.v2ray_metadata_switch.setChecked(
            config["floating_show_v2ray_metadata"]
        )
        self.layout_mode_combo.setCurrentText(
            "双行" if config["floating_layout_mode"] == "double" else "单行"
        )
        self.layout_scale_slider.setValue(config["floating_scale"])
        self._update_layout_scale_value(config["floating_scale"])
        self.font_size_input.setValue(config["floating_font_size"])
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
            self.source_status_label.setText(f"系统读取失败\n{snapshot.system_error}")
        elif snapshot.proxy_error:
            self.source_status_label.setText("系统在线 · V2Ray 离线")
            self.source_status_label.setToolTip(snapshot.proxy_error)
        elif not snapshot.v2rayn_enabled:
            self.source_status_label.setText("系统在线 · V2Ray 已关闭")
        else:
            self.source_status_label.setText("系统在线 · V2Ray 在线")
        if snapshot.app_monitor_available:
            app_status = f"ETW · {len(snapshot.applications)} 个活跃进程"
        else:
            app_status = snapshot.app_monitor_error or "ETW 不可用"
        self.app_status_label.setText(app_status)
        self.app_status_label.setToolTip(app_status)
        self._set_applications(snapshot.applications)
        if self._current_route == "history":
            now = time.monotonic()
            if now - self._last_history_request >= 1.5:
                self._request_history()

    def _set_applications(self, applications):
        now = time.monotonic()
        active_keys = set()
        for item in applications:
            key = (item.pid, item.app_key)
            active_keys.add(key)
            self._application_cache[key] = (item, now)
        visible = []
        for key, (item, last_seen) in tuple(self._application_cache.items()):
            if key not in active_keys:
                if now - last_seen > APPLICATION_IDLE_RETENTION_SECONDS:
                    del self._application_cache[key]
                    continue
                item = replace(
                    item,
                    upload_bytes=0,
                    download_bytes=0,
                    upload_speed=0.0,
                    download_speed=0.0,
                )
            visible.append(item)
        self._latest_applications = tuple(visible)
        active_keys = set()
        for item in visible:
            key = (item.pid, item.app_key)
            active_keys.add(key)
            previous = self._sort_scores.get(key)
            values = (item.total_speed, item.download_speed, item.upload_speed)
            if previous is None:
                self._sort_scores[key] = values
            else:
                self._sort_scores[key] = tuple(
                    old * 0.65 + current * 0.35
                    for old, current in zip(previous, values)
                )
        self._sort_scores = {
            key: value for key, value in self._sort_scores.items() if key in active_keys
        }
        mode = self.app_sort_combo.currentData() or "total"

        def sort_key(item):
            stable = (item.process_name.casefold(), item.pid)
            if mode == "name":
                return stable
            score = self._sort_scores.get((item.pid, item.app_key), (0, 0, 0))
            index = {"total": 0, "download": 1, "upload": 2}.get(mode, 0)
            return (-score[index], *stable)

        items = sorted(visible, key=sort_key)[:100]
        self._render_application_rows(items)

    def _render_application_rows(self, items):
        self.app_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = (
                item.process_name,
                str(item.pid),
                str(item.connection_count),
                format_rate(item.download_speed),
                format_rate(item.upload_speed),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column in (1, 2, 3, 4):
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if column == 0:
                    details = item.app_path or item.process_name
                    cell.setToolTip(
                        f"{details}\nPID {item.pid} · {item.connection_count} 个连接"
                    )
                self.app_table.setItem(row, column, cell)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 560
        self.app_table.setColumnHidden(1, compact)
        self.app_table.setColumnHidden(2, compact)

    def _resort_applications(self, *_args):
        mode = self.app_sort_combo.currentData() or "total"

        def sort_key(item):
            stable = (item.process_name.casefold(), item.pid)
            if mode == "name":
                return stable
            score = self._sort_scores.get((item.pid, item.app_key), (0, 0, 0))
            index = {"total": 0, "download": 1, "upload": 2}.get(mode, 0)
            return (-score[index], *stable)

        self._render_application_rows(
            sorted(self._latest_applications, key=sort_key)[:100]
        )

    def set_history_result(self, result):
        if isinstance(result, Exception):
            self.history_status.setText(f"历史查询失败：{result}")
            return
        if not isinstance(result, dict):
            self.history_status.setText("历史查询返回了无效数据")
            return
        source_labels = {
            "system": "系统总流量",
            "v2ray": "V2Ray 代理",
            "direct": "直连估算",
            "application": "应用合计",
        }
        self.history_status.setText(
            f"{source_labels.get(result.get('source'), '流量')} · {result.get('resolution', '--')} 粒度"
        )
        self.history_upload.setText(
            f"上传总量  {format_bytes(result.get('totalUploadBytes', 0))}"
        )
        self.history_download.setText(
            f"下载总量  {format_bytes(result.get('totalDownloadBytes', 0))}"
        )
        self.trend_chart.set_points(result.get("points", ()))
        self.ranking_chart.set_items(result.get("ranking", ()))
        self._history_loaded = True

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

    def _switch_page(self, route):
        self._current_route = str(route)
        self.stacked_widget.setCurrentWidget(self._page_map[self._current_route])
        if self._current_route == "history":
            self._request_history()

    def _request_history(self, *_args):
        range_key = self.history_range.currentData() or "hour"
        source = self.history_source.currentData() or "system"
        self._last_history_request = time.monotonic()
        if not self._history_loaded:
            self.history_status.setText("正在加载历史数据")
        self.history_requested.emit(str(range_key), str(source))

    def _save(self, *_args):
        display_modes = {
            "代理 + 直连": "proxy_direct",
            "系统 + 直连": "system_direct",
            "系统 + 代理": "system_proxy",
            "系统 + 代理 + 直连": "system_proxy_direct",
        }
        self.config_changed.emit(
            {
                "application_monitor_enabled": self.application_monitor_switch.isChecked(),
                "network_scope": (
                    "all_active"
                    if self.network_scope_combo.currentText() == "全部活动网卡"
                    else "default_route"
                ),
                "v2rayn_enabled": self.enabled_switch.isChecked(),
                "floating_enabled": self.floating_switch.isChecked(),
                "floating_locked": self.floating_lock_switch.isChecked(),
                "floating_display_mode": display_modes.get(
                    self.floating_display_combo.currentText(), "proxy_direct"
                ),
                "floating_show_v2ray_metadata": self.v2ray_metadata_switch.isChecked(),
                "floating_layout_mode": (
                    "double" if self.layout_mode_combo.currentText() == "双行" else "single"
                ),
                "floating_scale": self.layout_scale_slider.value(),
                "floating_font_size": self.font_size_input.value(),
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

    def _update_layout_scale_value(self, value):
        self.layout_scale_value.setText(f"{int(value)}%")


__all__ = [
    "NetworkMonitorWidget",
    "TrafficMetricCard",
    "TrafficRankingChart",
    "TrafficTrendChart",
    "format_bytes",
    "format_rate",
]
