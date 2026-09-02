from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QSizePolicy,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    Pivot,
    ProgressBar,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    ToolButton,
    TransparentToolButton,
)


def format_bytes(value):
    size = max(0.0, float(value or 0))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024.0


class MetricCard(SimpleCardWidget):
    def __init__(self, title, icon, color, parent=None):
        super().__init__(parent)
        self.setBorderRadius(8)
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(5)

        heading = QHBoxLayout()
        heading.setSpacing(8)
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(18, 18)
        heading.addWidget(icon_widget)
        heading.addWidget(CaptionLabel(title, self))
        heading.addStretch(1)
        layout.addLayout(heading)

        self.value = StrongBodyLabel("--", self)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.value)
        self.progress = ProgressBar(self, useAni=False)
        self.progress.setRange(0, 100)
        self.progress.setCustomBarColor(color, color)
        layout.addWidget(self.progress)

    def set_value(self, value, progress=None):
        self.value.setText(str(value))
        self.value.setToolTip(str(value))
        if progress is not None:
            self.progress.setValue(max(0, min(100, int(round(float(progress))))))


class PluginDiagnosticsWidget(QWidget):
    active_changed = Signal(bool)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("pluginDiagnosticsPage")
        self._metric_columns = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(SubtitleLabel("插件诊断", self))
        header.addStretch(1)
        refresh = TransparentToolButton(FluentIcon.SYNC, self)
        refresh.setToolTip("立即刷新")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.metrics = QGridLayout()
        self.metrics.setHorizontalSpacing(8)
        self.metrics.setVerticalSpacing(8)
        self.cpu = MetricCard("宿主 CPU", FluentIcon.SPEED_HIGH, "#00796B", self)
        self.memory = MetricCard("工作集", FluentIcon.PIE_SINGLE, "#3F6DB5", self)
        self.handles = MetricCard("句柄", FluentIcon.APPLICATION, "#B26A00", self)
        self.threads = MetricCard("线程", FluentIcon.SPEED_MEDIUM, "#2E7D32", self)
        self._metric_cards = (self.cpu, self.memory, self.handles, self.threads)
        self._arrange_metrics(2)
        layout.addLayout(self.metrics)

        toolbar = QHBoxLayout()
        self.pivot = Pivot(self)
        for route, text in (("plugins", "已加载插件"), ("runtime", "运行时"), ("errors", "错误日志")):
            self.pivot.addItem(routeKey=route, text=text)
        self.pivot.setCurrentItem("plugins")
        toolbar.addWidget(self.pivot)
        toolbar.addStretch(1)
        self.plugin_count = CaptionLabel("0 个插件", self)
        toolbar.addWidget(self.plugin_count)
        layout.addLayout(toolbar)

        self.page_stack = QStackedWidget(self)
        self.plugin_table = self._table(["插件", "ID", "版本", "模块", "来源"])
        self.runtime_table = self._table(["指标", "值"])
        self.errors = QPlainTextEdit(self)
        self.errors.setObjectName("diagnosticLog")
        self.errors.setReadOnly(True)
        self.errors.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.errors.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.errors.setFrameShape(QFrame.Shape.StyledPanel)

        self.page_stack.addWidget(self.plugin_table)
        self.page_stack.addWidget(self.runtime_table)
        self.page_stack.addWidget(self.errors)
        layout.addWidget(self.page_stack, 1)
        self.pivot.currentItemChanged.connect(self._switch)

    def showEvent(self, event):
        super().showEvent(event)
        self.active_changed.emit(True)

    def hideEvent(self, event):
        self.active_changed.emit(False)
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_metrics(4 if event.size().width() >= 760 else 2)
        self.plugin_table.setColumnHidden(4, event.size().width() < 760)

    def apply_snapshot(self, snapshot):
        process = snapshot["process"]
        self.cpu.set_value(f"{process['cpu_percent']:.1f}%", process["cpu_percent"])
        self.memory.set_value(format_bytes(process["working_set"]))
        self.memory.progress.setVisible(False)
        self.handles.set_value(str(process["handles"]))
        self.handles.progress.setVisible(False)
        self.threads.set_value(str(process["threads"]))
        self.threads.progress.setVisible(False)

        self.plugin_table.setRowCount(0)
        for row, plugin in enumerate(snapshot["plugins"]):
            self.plugin_table.insertRow(row)
            values = (
                plugin["name"],
                plugin["id"],
                plugin["version"],
                plugin["modules"],
                plugin["path"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.plugin_table.setItem(row, column, item)
        self.plugin_count.setText(f"{len(snapshot['plugins'])} 个插件")

        runtime = (
            ("私有字节", format_bytes(process["private_bytes"])),
            ("Python 对象", process["python_objects"]),
            ("已加载模块", process["loaded_modules"]),
            ("GC 计数", " / ".join(str(value) for value in process["gc_counts"])),
        )
        self.runtime_table.setRowCount(0)
        for row, values in enumerate(runtime):
            self.runtime_table.insertRow(row)
            self.runtime_table.setItem(row, 0, QTableWidgetItem(str(values[0])))
            self.runtime_table.setItem(row, 1, QTableWidgetItem(str(values[1])))
        self.errors.setPlainText("\n".join(snapshot["errors"]) or "没有错误日志")

    def show_error(self, message):
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.error("诊断失败", str(message), parent=self, position=InfoBarPosition.TOP)

    def _arrange_metrics(self, columns):
        if columns == self._metric_columns:
            return
        while self.metrics.count():
            self.metrics.takeAt(0)
        for index, card in enumerate(self._metric_cards):
            self.metrics.addWidget(card, index // columns, index % columns)
        for column in range(columns):
            self.metrics.setColumnStretch(column, 1)
        self._metric_columns = columns

    def _switch(self, route):
        page = {"plugins": 0, "runtime": 1, "errors": 2}.get(route, 0)
        self.page_stack.setCurrentIndex(page)

    def _table(self, headers):
        table = TableWidget(self)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setShowGrid(False)
        table.setBorderVisible(True)
        table.setBorderRadius(8)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(42)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(44)
        for column in range(len(headers) - 1):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
        return table


__all__ = ["PluginDiagnosticsWidget", "format_bytes"]
