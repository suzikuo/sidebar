from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
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
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    SearchLineEdit,
    SubtitleLabel,
    TableWidget,
    ToolButton,
    TransparentToolButton,
)

from .models import search_commands


class CommandDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("添加命令", self)
        self.name_edit = LineEdit(self)
        self.name_edit.setPlaceholderText("例如：打开工作目录")
        self.target_edit = LineEdit(self)
        self.target_edit.setPlaceholderText("程序路径或 URI")
        self.arguments_edit = LineEdit(self)
        self.arguments_edit.setPlaceholderText("可选")
        self.kind_combo = ComboBox(self)
        self.kind_combo.addItem("程序", userData="process")
        self.kind_combo.addItem("URI", userData="uri")

        form = QFormLayout()
        form.setContentsMargins(0, 8, 0, 0)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("名称", self.name_edit)
        form.addRow("类型", self.kind_combo)
        form.addRow("目标", self.target_edit)
        form.addRow("参数", self.arguments_edit)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("添加")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(460)

    def validate(self):
        return bool(self.name_edit.text().strip() and self.target_edit.text().strip())

    def value(self):
        return {
            "name": self.name_edit.text().strip(),
            "target": self.target_edit.text().strip(),
            "arguments": self.arguments_edit.text().strip(),
            "kind": self.kind_combo.currentData(),
        }


class CommandPaletteWidget(QWidget):
    execute_requested = Signal(dict)
    add_requested = Signal(dict)
    remove_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("commandPalettePage")
        self._commands = []
        self._visible_commands = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(SubtitleLabel("命令面板", self))
        header.addStretch(1)
        refresh = TransparentToolButton(FluentIcon.SYNC, self)
        refresh.setToolTip("刷新命令")
        refresh.clicked.connect(self.refresh_requested.emit)
        add = PrimaryPushButton(FluentIcon.ADD, "添加命令", self)
        add.clicked.connect(self._show_add_dialog)
        header.addWidget(refresh)
        header.addWidget(add)
        layout.addLayout(header)

        self.search = SearchLineEdit(self)
        self.search.setPlaceholderText("搜索命令、应用、书签或主机")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._execute_current)
        layout.addWidget(self.search)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(2, 0, 2, 0)
        self.result_count = CaptionLabel("0 项", self)
        status_row.addWidget(BodyLabel("结果", self))
        status_row.addStretch(1)
        status_row.addWidget(self.result_count)
        layout.addLayout(status_row)

        self.content_stack = QStackedWidget(self)
        self.table = TableWidget(self.content_stack)
        self.table.setObjectName("commandTable")
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["命令", "来源", "说明", "操作"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.cellDoubleClicked.connect(lambda *_: self._execute_current())
        table_header = self.table.horizontalHeader()
        table_header.setMinimumSectionSize(44)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table_header.resizeSection(3, 74)

        self.empty_view = QWidget(self.content_stack)
        empty_layout = QVBoxLayout(self.empty_view)
        empty_layout.setContentsMargins(20, 20, 20, 20)
        empty_layout.addStretch(1)
        empty_icon = IconWidget(FluentIcon.SEARCH, self.empty_view)
        empty_icon.setFixedSize(28, 28)
        empty_layout.addWidget(empty_icon, 0, Qt.AlignmentFlag.AlignCenter)
        self.empty_label = CaptionLabel("没有匹配的命令", self.empty_view)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addStretch(1)

        self.content_stack.addWidget(self.table)
        self.content_stack.addWidget(self.empty_view)
        layout.addWidget(self.content_stack, 1)

    def set_commands(self, commands):
        self._commands = list(commands or ())
        self._refresh()

    def show_error(self, message):
        from qfluentwidgets import InfoBar, InfoBarPosition

        InfoBar.error("命令执行失败", str(message), parent=self, position=InfoBarPosition.TOP)

    def _refresh(self, *_args):
        self._visible_commands = search_commands(self._commands, self.search.text())
        self.table.setRowCount(0)
        for row, command in enumerate(self._visible_commands):
            self.table.insertRow(row)
            values = (
                command.get("name", ""),
                command.get("category", ""),
                command.get("subtitle", ""),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
            self.table.setCellWidget(row, 3, self._action_widget(command))
        count = len(self._visible_commands)
        self.result_count.setText(f"{count} 项")
        self.content_stack.setCurrentWidget(self.table if count else self.empty_view)
        if count:
            self.table.selectRow(0)

    def _action_widget(self, command):
        widget = QWidget(self.table)
        widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Preferred)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        run_button = ToolButton(FluentIcon.PLAY, widget)
        run_button.setToolTip("执行")
        run_button.clicked.connect(lambda _=False, value=command: self.execute_requested.emit(value))
        layout.addWidget(run_button)
        if command.get("custom"):
            delete_button = ToolButton(FluentIcon.DELETE, widget)
            delete_button.setToolTip("删除")
            delete_button.clicked.connect(
                lambda _=False, command_id=command["id"]: self.remove_requested.emit(command_id)
            )
            layout.addWidget(delete_button)
        return widget

    def _execute_current(self):
        row = self.table.currentRow()
        if row < 0 and self._visible_commands:
            row = 0
        if 0 <= row < len(self._visible_commands):
            self.execute_requested.emit(self._visible_commands[row])

    def _show_add_dialog(self):
        dialog = CommandDialog(self.window())
        if dialog.exec() and dialog.validate():
            self.add_requested.emit(dialog.value())


__all__ = ["CommandPaletteWidget"]
