import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    CardWidget,
    FlowLayout,
    FluentIcon,
    IconWidget,
    LineEdit,
    MessageBoxBase,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
    TransparentToolButton,
)


class AppEditDialog(MessageBoxBase):
    """Dialog to add or edit an application"""

    def __init__(self, parent=None, app_data=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("Add Application", self)

        # Name
        self.nameEdit = LineEdit(self)
        self.nameEdit.setPlaceholderText("Application Name")

        # Path
        self.pathLayout = QHBoxLayout()
        self.pathEdit = LineEdit(self)
        self.pathEdit.setPlaceholderText("Executable Path (e.g. C:\\Path\\App.exe)")
        self.browseBtn = PushButton("Browse", self, FluentIcon.FOLDER)
        self.browseBtn.clicked.connect(self._on_browse)
        self.pathLayout.addWidget(self.pathEdit)
        self.pathLayout.addWidget(self.browseBtn)

        # Arguments
        self.argsEdit = LineEdit(self)
        self.argsEdit.setPlaceholderText("Arguments (Optional)")

        # Add widgets to view layout
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(StrongBodyLabel("Name:", self))
        self.viewLayout.addWidget(self.nameEdit)
        self.viewLayout.addWidget(StrongBodyLabel("Path:", self))
        self.viewLayout.addLayout(self.pathLayout)
        self.viewLayout.addWidget(StrongBodyLabel("Arguments:", self))
        self.viewLayout.addWidget(self.argsEdit)

        self.widget.setMinimumWidth(400)

        # Populate if editing
        if app_data:
            self.titleLabel.setText("Edit Application")
            self.nameEdit.setText(app_data.get("name", ""))
            self.pathEdit.setText(app_data.get("exe_path", ""))
            self.argsEdit.setText(app_data.get("arguments", ""))

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Executable", "", "Executables (*.exe);;All Files (*)"
        )
        if path:
            self.pathEdit.setText(os.path.normpath(path))

            # Auto-fill name if empty
            if not self.nameEdit.text():
                name = os.path.splitext(os.path.basename(path))[0]
                self.nameEdit.setText(name.title())

    def get_data(self):
        return {
            "name": self.nameEdit.text(),
            "exe_path": self.pathEdit.text(),
            "arguments": self.argsEdit.text(),
        }


class AppCard(CardWidget):
    """Card widget representing a single application"""

    launch_clicked = Signal(str)
    edit_clicked = Signal(str)
    delete_clicked = Signal(str)

    def __init__(self, app_data, parent=None):
        super().__init__(parent)
        self.app_data = app_data
        self.app_id = app_data.get("id")

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(16, 12, 16, 12)
        self.layout.setSpacing(12)

        # Icon
        self.iconLabel = IconWidget(FluentIcon.TILES, self)
        self.iconLabel.setFixedSize(32, 32)

        # Info
        self.infoLayout = QVBoxLayout()
        self.infoLayout.setSpacing(2)
        self.nameLabel = StrongBodyLabel(app_data.get("name", "Unknown App"), self)
        self.pathLabel = CaptionLabel(app_data.get("exe_path", ""), self)
        self.pathLabel.setTextColor("#808080", "#909090")  # Manual dim color
        self.infoLayout.addWidget(self.nameLabel)
        self.infoLayout.addWidget(self.pathLabel)
        self.infoLayout.addStretch(1)

        # Buttons
        self.launchBtn = TransparentToolButton(FluentIcon.PLAY, self)
        self.launchBtn.setToolTip("Launch")
        self.launchBtn.clicked.connect(lambda: self.launch_clicked.emit(self.app_id))

        self.editBtn = TransparentToolButton(FluentIcon.EDIT, self)
        self.editBtn.setToolTip("Edit")
        self.editBtn.clicked.connect(lambda: self.edit_clicked.emit(self.app_id))

        self.deleteBtn = TransparentToolButton(FluentIcon.DELETE, self)
        self.deleteBtn.setToolTip("Delete")
        self.deleteBtn.clicked.connect(lambda: self.delete_clicked.emit(self.app_id))

        self.layout.addWidget(self.iconLabel)
        self.layout.addLayout(self.infoLayout)
        self.layout.addStretch(1)
        self.layout.addWidget(self.launchBtn)
        self.layout.addWidget(self.editBtn)
        self.layout.addWidget(self.deleteBtn)

        self.setFixedHeight(80)


class AppLauncherWidget(QWidget):
    """Main Widget for App Launcher"""

    app_added = Signal(dict)
    app_removed = Signal(str)
    app_updated = Signal(str, dict)
    launch_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.apps = []

        self.vLayout = QVBoxLayout(self)
        self.vLayout.setContentsMargins(30, 30, 30, 30)
        self.vLayout.setSpacing(20)

        # Header
        self.headerLayout = QHBoxLayout()
        self.titleLabel = TitleLabel("App Launcher", self)
        self.addBtn = PrimaryPushButton(FluentIcon.ADD, "Add App", self)
        self.addBtn.clicked.connect(self._show_add_dialog)

        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.addBtn)
        self.vLayout.addLayout(self.headerLayout)

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("Search applications")
        self.searchEdit.textChanged.connect(self._refresh_list)
        self.vLayout.addWidget(self.searchEdit)

        # Scroll Area for apps
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent;")

        self.scrollWidget = QWidget()
        self.scrollWidget.setStyleSheet("background: transparent;")
        self.flowLayout = FlowLayout(self.scrollWidget, needAni=True)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setVerticalSpacing(10)
        self.flowLayout.setHorizontalSpacing(10)

        self.scroll.setWidget(self.scrollWidget)
        self.vLayout.addWidget(self.scroll)

        self.emptyLabel = CaptionLabel("No applications", self)
        self.emptyLabel.setAlignment(Qt.AlignCenter)
        self.emptyLabel.hide()
        self.vLayout.addWidget(self.emptyLabel)

    def set_apps(self, apps: list):
        self.apps = list(apps or [])
        self._refresh_list()

    def _refresh_list(self, _query=""):
        # Clear existing
        self.flowLayout.takeAllWidgets()

        query = self.searchEdit.text().strip().lower()
        visible_count = 0

        for app in self.apps:
            searchable = " ".join(
                str(app.get(key, "")) for key in ("name", "exe_path", "arguments")
            ).lower()
            if query and query not in searchable:
                continue
            card = AppCard(app, self.scrollWidget)
            card.launch_clicked.connect(self.launch_requested)
            card.edit_clicked.connect(self._show_edit_dialog)
            card.delete_clicked.connect(self.app_removed)
            # Make card stretch to fill width in flow layout if you want list style
            # Or fixed width for grid. Let's try to set a reasonable width
            card.setFixedWidth(300)
            self.flowLayout.addWidget(card)
            visible_count += 1

        self.emptyLabel.setText("No matching applications" if query else "No applications")
        self.emptyLabel.setVisible(visible_count == 0)

    def _show_add_dialog(self):
        w = AppEditDialog(self.window())
        if w.exec():
            data = w.get_data()
            if data["name"] and data["exe_path"]:
                self.app_added.emit(data)

    def _show_edit_dialog(self, app_id):
        app = next((a for a in self.apps if a["id"] == app_id), None)
        if not app:
            return

        w = AppEditDialog(self.window(), app)
        if w.exec():
            data = w.get_data()
            if data["name"] and data["exe_path"]:
                self.app_updated.emit(app_id, data)
