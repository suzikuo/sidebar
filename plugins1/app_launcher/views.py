import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ComboBox,
    FluentIcon,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
    TableWidget,
    TextEdit,
    TitleLabel,
    ToolButton,
)


def find_default_chrome_path() -> str:
    candidates = [
        os.path.join(
            os.environ.get("ProgramFiles", ""),
            "Google",
            "Chrome",
            "Application",
            "chrome.exe",
        ),
        os.path.join(
            os.environ.get("ProgramFiles(x86)", ""),
            "Google",
            "Chrome",
            "Application",
            "chrome.exe",
        ),
        os.path.join(
            os.environ.get("LocalAppData", ""),
            "Google",
            "Chrome",
            "Application",
            "chrome.exe",
        ),
    ]
    return next((path for path in candidates if path and os.path.exists(path)), "")


def extract_app_url(arguments: str) -> str:
    for token in str(arguments or "").split():
        if token.startswith("--app="):
            return token.removeprefix("--app=").strip('"')
    return ""


class AppEditDialog(MessageBoxBase):
    """Dialog to add or edit an application."""

    APP_TYPE_NORMAL = "application"
    APP_TYPE_CHROME = "chrome"

    def __init__(self, parent=None, app_data=None, preset_type=APP_TYPE_NORMAL):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Edit Application" if app_data else "Add Application", self)

        initial_type = (app_data or {}).get("app_type") or preset_type
        if initial_type not in (self.APP_TYPE_NORMAL, self.APP_TYPE_CHROME):
            initial_type = self.APP_TYPE_NORMAL

        self.typeCombo = ComboBox(self)
        self.typeCombo.addItem("Application", userData=self.APP_TYPE_NORMAL)
        self.typeCombo.addItem("Chrome App", userData=self.APP_TYPE_CHROME)
        self._select_type(initial_type)
        self.typeCombo.currentIndexChanged.connect(self._sync_type_fields)

        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText("Name")

        self.pathRow = QWidget(self)
        self.pathLayout = QHBoxLayout(self.pathRow)
        self.pathLayout.setContentsMargins(0, 0, 0, 0)
        self.pathLayout.setSpacing(8)
        self.pathEdit = LineEdit(self.pathRow)
        self.pathEdit.setPlaceholderText("Executable path")
        self.browseBtn = PushButton("Browse", self.pathRow, FluentIcon.FOLDER)
        self.browseBtn.clicked.connect(self._on_browse_exe)
        self.pathLayout.addWidget(self.pathEdit, 1)
        self.pathLayout.addWidget(self.browseBtn)

        self.argsEdit = TextEdit(self)
        self.argsEdit.setPlaceholderText("Arguments")
        self.argsEdit.setFixedHeight(76)

        self.useAhkCheck = QCheckBox("Use AutoHotkey window adjustment", self)
        self.useAhkCheck.toggled.connect(self._sync_ahk_fields)

        self.ahkPathRow = QWidget(self)
        self.ahkPathLayout = QHBoxLayout(self.ahkPathRow)
        self.ahkPathLayout.setContentsMargins(0, 0, 0, 0)
        self.ahkPathLayout.setSpacing(8)
        self.ahkPathEdit = LineEdit(self.ahkPathRow)
        self.ahkPathEdit.setPlaceholderText("Optional AutoHotkey.exe path")
        self.browseAhkBtn = PushButton("Browse", self.ahkPathRow, FluentIcon.FOLDER)
        self.browseAhkBtn.clicked.connect(self._on_browse_ahk)
        self.ahkPathLayout.addWidget(self.ahkPathEdit, 1)
        self.ahkPathLayout.addWidget(self.browseAhkBtn)

        self.windowRow = QWidget(self)
        self.windowLayout = QHBoxLayout(self.windowRow)
        self.windowLayout.setContentsMargins(0, 0, 0, 0)
        self.windowLayout.setSpacing(8)
        self.xSpin = self._spin_box(0, 9999, 200)
        self.ySpin = self._spin_box(0, 9999, 200)
        self.widthSpin = self._spin_box(1, 9999, 160)
        self.heightSpin = self._spin_box(1, 9999, 400)
        for label, spin in (
            ("X", self.xSpin),
            ("Y", self.ySpin),
            ("W", self.widthSpin),
            ("H", self.heightSpin),
        ):
            self.windowLayout.addWidget(BodyLabel(label, self.windowRow))
            self.windowLayout.addWidget(spin)
        self.windowLayout.addStretch(1)

        self.alwaysOnTopCheck = QCheckBox("Always on top", self)

        self.formLayout = QFormLayout()
        self.formLayout.setContentsMargins(0, 8, 0, 0)
        self.formLayout.setSpacing(10)
        self.formLayout.addRow("Type:", self.typeCombo)
        self.formLayout.addRow("Name:", self.nameEdit)
        self.formLayout.addRow("Path:", self.pathRow)
        self.formLayout.addRow("Arguments:", self.argsEdit)
        self.formLayout.addRow("", self.useAhkCheck)
        self.formLayout.addRow("AHK:", self.ahkPathRow)
        self.formLayout.addRow("Window:", self.windowRow)
        self.formLayout.addRow("", self.alwaysOnTopCheck)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addLayout(self.formLayout)
        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(560)

        self._load_data(app_data, initial_type)
        self._sync_type_fields()

    def _spin_box(self, minimum: int, maximum: int, value: int) -> QSpinBox:
        spin = QSpinBox(self)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setFixedWidth(72)
        return spin

    def _select_type(self, app_type: str):
        for index in range(self.typeCombo.count()):
            if self.typeCombo.itemData(index) == app_type:
                self.typeCombo.setCurrentIndex(index)
                return

    def _load_data(self, app_data, initial_type: str):
        if app_data:
            self.nameEdit.setText(app_data.get("name", ""))
            self.pathEdit.setText(app_data.get("exe_path", ""))
            self.argsEdit.setPlainText(app_data.get("arguments", ""))
            self.useAhkCheck.setChecked(bool(app_data.get("use_ahk", False)))
            self.ahkPathEdit.setText(app_data.get("ahk_path", ""))
            self.xSpin.setValue(int(app_data.get("window_x", 200)))
            self.ySpin.setValue(int(app_data.get("window_y", 200)))
            self.widthSpin.setValue(int(app_data.get("window_width", 160)))
            self.heightSpin.setValue(int(app_data.get("window_height", 400)))
            self.alwaysOnTopCheck.setChecked(bool(app_data.get("always_on_top", True)))
            return

        if initial_type == self.APP_TYPE_CHROME:
            self.titleLabel.setText("Add Chrome App")
            self.nameEdit.setText("linux.do")
            self.pathEdit.setText(find_default_chrome_path())
            self.argsEdit.setPlainText(
                '--window-size=300,600 --app=https://linux.do/ --user-data-dir="%TEMP%\\linuxdo-app"'
            )
            self.useAhkCheck.setChecked(True)
            self.alwaysOnTopCheck.setChecked(True)

    def _sync_type_fields(self):
        is_chrome = self.typeCombo.currentData() == self.APP_TYPE_CHROME
        self.useAhkCheck.setVisible(is_chrome)
        for widget in (self.ahkPathRow, self.windowRow, self.alwaysOnTopCheck):
            label = self._form_label_for(widget)
            if label:
                label.setVisible(is_chrome)
            widget.setVisible(is_chrome)
        if is_chrome and not self.pathEdit.text().strip():
            self.pathEdit.setText(find_default_chrome_path())
        self._sync_ahk_fields()

    def _sync_ahk_fields(self):
        enabled = self.typeCombo.currentData() == self.APP_TYPE_CHROME and self.useAhkCheck.isChecked()
        for widget in (self.ahkPathEdit, self.browseAhkBtn, self.xSpin, self.ySpin, self.widthSpin, self.heightSpin, self.alwaysOnTopCheck):
            widget.setEnabled(enabled)

    def _form_label_for(self, widget):
        return self.formLayout.labelForField(widget)

    def _on_browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable", "", "Executables (*.exe);;All Files (*)"
        )
        if path:
            self.pathEdit.setText(os.path.normpath(path))
            if not self.nameEdit.text().strip():
                name = os.path.splitext(os.path.basename(path))[0]
                self.nameEdit.setText(name.title())

    def _on_browse_ahk(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select AutoHotkey", "", "Executables (*.exe);;All Files (*)"
        )
        if path:
            self.ahkPathEdit.setText(os.path.normpath(path))

    def get_data(self):
        app_type = self.typeCombo.currentData() or self.APP_TYPE_NORMAL
        return {
            "app_type": app_type,
            "name": self.nameEdit.text().strip(),
            "exe_path": self.pathEdit.text().strip(),
            "arguments": self.argsEdit.toPlainText().strip(),
            "use_ahk": app_type == self.APP_TYPE_CHROME and self.useAhkCheck.isChecked(),
            "ahk_path": self.ahkPathEdit.text().strip(),
            "window_x": self.xSpin.value(),
            "window_y": self.ySpin.value(),
            "window_width": self.widthSpin.value(),
            "window_height": self.heightSpin.value(),
            "always_on_top": self.alwaysOnTopCheck.isChecked(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["name"] and data["exe_path"])


class AppLauncherWidget(QWidget):
    """Main widget for App Launcher."""

    app_added = Signal(dict)
    app_removed = Signal(str)
    app_updated = Signal(str, dict)
    launch_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.apps = []

        self.vLayout = QVBoxLayout(self)
        self.vLayout.setContentsMargins(18, 16, 18, 14)
        self.vLayout.setSpacing(10)

        self.headerLayout = QHBoxLayout()
        self.titleLabel = TitleLabel("App Launcher", self)
        self.addBtn = PrimaryPushButton(FluentIcon.ADD, "Add App", self)
        self.addChromeBtn = PushButton("Add Chrome", self, FluentIcon.ADD)
        self.addBtn.clicked.connect(self._show_add_dialog)
        self.addChromeBtn.clicked.connect(self._show_add_chrome_dialog)

        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.addChromeBtn)
        self.headerLayout.addWidget(self.addBtn)
        self.vLayout.addLayout(self.headerLayout)

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("Search name, path, or arguments")
        self.searchEdit.textChanged.connect(self._refresh_table)
        self.vLayout.addWidget(self.searchEdit)

        self.table = TableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Target", "Arguments", "Actions"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.cellDoubleClicked.connect(self._launch_row)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.vLayout.addWidget(self.table, 1)

        self.emptyLabel = CaptionLabel("No applications", self)
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.emptyLabel.hide()
        self.vLayout.addWidget(self.emptyLabel)

    def set_apps(self, apps: list):
        self.apps = list(apps or [])
        self._refresh_table()

    def _refresh_table(self, _query=""):
        query = self.searchEdit.text().strip().lower()
        visible_apps = []
        for app in self.apps:
            searchable = " ".join(
                str(app.get(key, "")) for key in ("name", "exe_path", "arguments", "app_type")
            ).lower()
            if not query or query in searchable:
                visible_apps.append(app)

        self.table.setRowCount(0)
        for row, app in enumerate(visible_apps):
            self.table.insertRow(row)
            app_id = app.get("id", "")
            app_type = app.get("app_type") or "application"
            type_text = "Chrome" if app_type == "chrome" else "App"
            target = extract_app_url(app.get("arguments", "")) if app_type == "chrome" else ""
            if not target:
                target = app.get("exe_path", "")

            self._set_item(row, 0, app.get("name", "Unknown App"), app_id)
            self._set_item(row, 1, type_text, app_id)
            self._set_item(row, 2, target, app_id)
            self._set_item(row, 3, app.get("arguments", ""), app_id)
            self.table.setCellWidget(row, 4, self._action_widget(app))

        self.emptyLabel.setText("No matching applications" if query else "No applications")
        self.emptyLabel.setVisible(not visible_apps)

    def _set_item(self, row: int, column: int, text: str, app_id: str):
        item = QTableWidgetItem(str(text or ""))
        item.setData(Qt.ItemDataRole.UserRole, app_id)
        item.setToolTip(str(text or ""))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, column, item)

    def _action_widget(self, app):
        widget = QWidget(self.table)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        launch_btn = ToolButton(FluentIcon.PLAY, widget)
        launch_btn.setToolTip("Launch")
        launch_btn.clicked.connect(lambda checked=False, app_id=app.get("id", ""): self.launch_requested.emit(app_id))

        edit_btn = ToolButton(FluentIcon.EDIT, widget)
        edit_btn.setToolTip("Edit")
        edit_btn.clicked.connect(lambda checked=False, app_id=app.get("id", ""): self._show_edit_dialog(app_id))

        delete_btn = ToolButton(FluentIcon.DELETE, widget)
        delete_btn.setToolTip("Delete")
        delete_btn.clicked.connect(lambda checked=False, app_id=app.get("id", ""): self.app_removed.emit(app_id))

        layout.addWidget(launch_btn)
        layout.addWidget(edit_btn)
        layout.addWidget(delete_btn)
        layout.addStretch(1)
        return widget

    def _launch_row(self, row: int, _column: int):
        item = self.table.item(row, 0)
        if item:
            self.launch_requested.emit(item.data(Qt.ItemDataRole.UserRole))

    def _show_add_dialog(self):
        dialog = AppEditDialog(self.window())
        if dialog.exec():
            data = dialog.get_data()
            if data["name"] and data["exe_path"]:
                self.app_added.emit(data)

    def _show_add_chrome_dialog(self):
        dialog = AppEditDialog(self.window(), preset_type=AppEditDialog.APP_TYPE_CHROME)
        if dialog.exec():
            data = dialog.get_data()
            if data["name"] and data["exe_path"]:
                self.app_added.emit(data)

    def _show_edit_dialog(self, app_id):
        app = next((a for a in self.apps if a["id"] == app_id), None)
        if not app:
            return

        dialog = AppEditDialog(self.window(), app)
        if dialog.exec():
            data = dialog.get_data()
            if data["name"] and data["exe_path"]:
                self.app_updated.emit(app_id, data)
