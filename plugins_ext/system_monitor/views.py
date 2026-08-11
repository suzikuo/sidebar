from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QSizePolicy,
    QStackedWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    IconWidget,
    MessageBox,
    Pivot,
    ProgressBar,
    SearchLineEdit,
    SimpleCardWidget,
    StrongBodyLabel,
    SubtitleLabel,
    TableWidget,
    ToolButton,
    TransparentToolButton,
)


def format_bytes(value):
    size = max(0.0, float(value or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0


class MetricCard(SimpleCardWidget):
    def __init__(self, title, icon, color, show_progress=True, parent=None):
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

        value_row = QHBoxLayout()
        value_row.setSpacing(8)
        self.value = StrongBodyLabel("--", self)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.detail = CaptionLabel("", self)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.detail.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        value_row.addWidget(self.value, 1)
        value_row.addWidget(self.detail, 1)
        layout.addLayout(value_row)

        self.progress = ProgressBar(self, useAni=False)
        self.progress.setRange(0, 100)
        self.progress.setCustomBarColor(color, color)
        self.progress.setVisible(show_progress)
        layout.addWidget(self.progress)

    def set_value(self, value, progress=None, detail=""):
        self.value.setText(str(value))
        self.value.setToolTip(str(value))
        self.detail.setText(str(detail))
        self.detail.setToolTip(str(detail))
        if progress is not None:
            self.progress.setValue(max(0, min(100, int(round(float(progress))))))


class SystemMonitorWidget(QWidget):
    active_changed = Signal(bool)
    refresh_requested = Signal()
    interval_changed = Signal(int)
    terminate_requested = Signal(int)

    def __init__(self, interval_ms=2000, parent=None):
        super().__init__(parent)
        self.setObjectName("systemMonitorPage")
        self._processes = []
        self._metric_columns = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(SubtitleLabel("系统监控", self))
        header.addStretch(1)
        self.interval = ComboBox(self)
        self.interval.setMinimumWidth(86)
        for text, value in (("1 秒", 1000), ("2 秒", 2000), ("5 秒", 5000)):
            self.interval.addItem(text, userData=value)
            if value == interval_ms:
                self.interval.setCurrentIndex(self.interval.count() - 1)
        self.interval.currentIndexChanged.connect(
            lambda _index: self.interval_changed.emit(int(self.interval.currentData()))
        )
        refresh = TransparentToolButton(FluentIcon.SYNC, self)
        refresh.setToolTip("立即刷新")
        refresh.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.interval)
        header.addWidget(refresh)
        layout.addLayout(header)

        self.metrics = QGridLayout()
        self.metrics.setHorizontalSpacing(8)
        self.metrics.setVerticalSpacing(8)
        self.cpu_card = MetricCard("CPU", FluentIcon.SPEED_HIGH, "#00796B", parent=self)
        self.memory_card = MetricCard("内存", FluentIcon.PIE_SINGLE, "#3F6DB5", parent=self)
        self.process_card = MetricCard(
            "进程", FluentIcon.APPLICATION, "#2E7D32", show_progress=False, parent=self
        )
        self.disk_card = MetricCard("磁盘", FluentIcon.FOLDER, "#B26A00", parent=self)
        self._metric_cards = (
            self.cpu_card,
            self.memory_card,
            self.process_card,
            self.disk_card,
        )
        self._arrange_metrics(2)
        layout.addLayout(self.metrics)

        self.pivot = Pivot(self)
        self.pivot.addItem(routeKey="processes", text="进程")
        self.pivot.addItem(routeKey="disks", text="磁盘")
        self.pivot.setCurrentItem("processes")
        layout.addWidget(self.pivot)

        self.page_stack = QStackedWidget(self)
        self.process_view = QWidget(self.page_stack)
        process_layout = QVBoxLayout(self.process_view)
        process_layout.setContentsMargins(0, 0, 0, 0)
        process_layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = SearchLineEdit(self.process_view)
        self.search.setPlaceholderText("按名称或 PID 筛选")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._render_processes)
        self.process_count = CaptionLabel("0 个进程", self.process_view)
        self.terminate_button = ToolButton(FluentIcon.DELETE, self.process_view)
        self.terminate_button.setToolTip("结束选中进程")
        self.terminate_button.setEnabled(False)
        self.terminate_button.clicked.connect(self._confirm_terminate)
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.process_count)
        toolbar.addWidget(self.terminate_button)
        process_layout.addLayout(toolbar)
        self.process_table = self._table(["进程", "PID", "CPU", "内存", "线程"])
        self.process_table.itemSelectionChanged.connect(self._update_terminate_state)
        process_layout.addWidget(self.process_table, 1)

        self.disk_view = QWidget(self.page_stack)
        disk_layout = QVBoxLayout(self.disk_view)
        disk_layout.setContentsMargins(0, 0, 0, 0)
        self.disk_table = self._table(["磁盘", "已用", "可用", "容量", "占用"])
        disk_layout.addWidget(self.disk_table)

        self.page_stack.addWidget(self.process_view)
        self.page_stack.addWidget(self.disk_view)
        layout.addWidget(self.page_stack, 1)
        self.pivot.currentItemChanged.connect(self._switch_view)

    def showEvent(self, event):
        super().showEvent(event)
        self.active_changed.emit(True)

    def hideEvent(self, event):
        self.active_changed.emit(False)
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_metrics(4 if event.size().width() >= 760 else 2)

    def apply_snapshot(self, snapshot):
        memory = snapshot["memory"]
        disks = snapshot["disks"]
        self.cpu_card.set_value(
            f"{snapshot['cpu_percent']:.1f}%",
            snapshot["cpu_percent"],
            "系统",
        )
        self.memory_card.set_value(
            f"{memory['percent']:.1f}%",
            memory["percent"],
            f"{format_bytes(memory['used'])} / {format_bytes(memory['total'])}",
        )
        self.process_card.set_value(str(snapshot["process_count"]), detail="运行中")
        disk_percent = max((item["percent"] for item in disks), default=0.0)
        self.disk_card.set_value(
            f"{disk_percent:.1f}%",
            disk_percent,
            f"{len(disks)} 个卷",
        )
        self._processes = snapshot["processes"]
        self._render_processes()
        self.disk_table.setRowCount(0)
        for row, disk in enumerate(disks):
            self.disk_table.insertRow(row)
            values = (
                disk["root"],
                format_bytes(disk["used"]),
                format_bytes(disk["free"]),
                format_bytes(disk["total"]),
                f"{disk['percent']:.1f}%",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.disk_table.setItem(row, column, item)

    def show_error(self, message):
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.error("采样失败", str(message), parent=self, position=InfoBarPosition.TOP)

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

    def _render_processes(self, *_args):
        query = self.search.text().strip().casefold()
        visible = [
            item
            for item in self._processes
            if not query or query in item["name"].casefold() or query in str(item["pid"])
        ]
        self.process_table.setRowCount(0)
        for row, process in enumerate(visible):
            self.process_table.insertRow(row)
            values = (
                process["name"],
                process["pid"],
                f"{process['cpu_percent']:.1f}%",
                format_bytes(process["memory_bytes"]),
                process["threads"],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.ItemDataRole.UserRole, process["pid"])
                item.setToolTip(str(value))
                self.process_table.setItem(row, column, item)
        self.process_count.setText(f"{len(visible)} 个进程")
        self._update_terminate_state()

    def _update_terminate_state(self):
        self.terminate_button.setEnabled(self.process_table.currentRow() >= 0)

    def _confirm_terminate(self):
        row = self.process_table.currentRow()
        item = self.process_table.item(row, 0) if row >= 0 else None
        if item is None:
            return
        pid = int(item.data(Qt.ItemDataRole.UserRole))
        if MessageBox("结束进程", f"确定结束 {item.text()}（PID {pid}）？", self.window()).exec():
            self.terminate_requested.emit(pid)

    def _switch_view(self, route):
        self.page_stack.setCurrentWidget(
            self.process_view if route == "processes" else self.disk_view
        )

    def _table(self, headers):
        table = TableWidget(self)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setShowGrid(False)
        table.setFrameShape(QFrame.Shape.NoFrame)
        table.setBorderVisible(True)
        table.setBorderRadius(8)
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(42)
        header = table.horizontalHeader()
        header.setMinimumSectionSize(44)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        return table


__all__ = ["SystemMonitorWidget", "format_bytes"]
