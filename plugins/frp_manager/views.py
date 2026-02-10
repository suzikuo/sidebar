import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FlowLayout,
    FluentIcon,
    IconWidget,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PushButton,
    RoundMenu,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
)

from ui.components.base_widget import BScrollArea


class FRPConfigTile(CardWidget):
    """A tile representing an FRP configuration."""

    start_requested = Signal(int)
    stop_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    edit_config_requested = Signal(int)

    def __init__(
        self,
        config_id,
        name,
        exe_path,
        config_path,
        is_running,
        remarks="",
        parent=None,
    ):
        super().__init__(parent)
        self.config_id = config_id
        self.setFixedSize(240, 150)
        self.setCursor(Qt.PointingHandCursor)

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(15, 12, 15, 12)
        self.mainLayout.setSpacing(4)

        # Header: Icon + Name + Status
        header_layout = QHBoxLayout()
        icon = IconWidget(FluentIcon.IOT, self)
        icon.setFixedSize(20, 20)

        self.name_label = StrongBodyLabel(name, self)

        self.status_dot = QWidget(self)
        self.status_dot.setFixedSize(10, 10)
        self._set_status_style(is_running)

        header_layout.addWidget(icon)
        header_layout.addWidget(self.name_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.status_dot)
        self.mainLayout.addLayout(header_layout)

        # Details
        exe_label = CaptionLabel(f"EXE: {os.path.basename(exe_path)}", self)
        self.mainLayout.addWidget(exe_label)

        cfg_label = CaptionLabel(f"CFG: {os.path.basename(config_path)}", self)
        self.mainLayout.addWidget(cfg_label)

        if remarks:
            remarks_label = CaptionLabel(remarks, self)
            remarks_label.setWordWrap(True)
            self.mainLayout.addWidget(remarks_label)

        self.mainLayout.addStretch(1)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)

        if is_running:
            self.toggle_btn = TransparentToolButton(FluentIcon.PAUSE, self)
            self.toggle_btn.setToolTip("Stop")
            self.toggle_btn.clicked.connect(
                lambda: self.stop_requested.emit(self.config_id)
            )
        else:
            self.toggle_btn = TransparentToolButton(FluentIcon.PLAY, self)
            self.toggle_btn.setToolTip("Start")
            self.toggle_btn.clicked.connect(
                lambda: self.start_requested.emit(self.config_id)
            )

        self.edit_btn = TransparentToolButton(FluentIcon.EDIT, self)
        self.edit_btn.clicked.connect(lambda: self.edit_requested.emit(self.config_id))

        btn_layout.addWidget(self.toggle_btn)
        btn_layout.addWidget(self.edit_btn)
        self.mainLayout.addLayout(btn_layout)

    def _set_status_style(self, is_running):
        color = "#107c10" if is_running else "#d13438"
        self.status_dot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        edit_cfg_action = Action(FluentIcon.EDIT, "Edit Config File", self)
        delete_action = Action(FluentIcon.DELETE, "Delete", self)

        edit_cfg_action.triggered.connect(
            lambda: self.edit_config_requested.emit(self.config_id)
        )
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.config_id)
        )

        menu.addAction(edit_cfg_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        menu.exec(e.globalPos())


class FRPConfigDialog(MessageBoxBase):
    """Dialog to add or edit an FRP configuration."""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("FRP Configuration Settings", self)

        self.nameInput = LineEdit(self)
        self.nameInput.setPlaceholderText("Configuration Name")

        self.exePathInput = LineEdit(self)
        self.exePathInput.setPlaceholderText("Path to frpc.exe")
        self.exeBrowseBtn = PushButton("Browse", self)
        self.exeBrowseBtn.clicked.connect(self._on_browse_exe)

        exe_layout = QHBoxLayout()
        exe_layout.addWidget(self.exePathInput)
        exe_layout.addWidget(self.exeBrowseBtn)

        self.configPathInput = LineEdit(self)
        self.configPathInput.setPlaceholderText("Path to frpc.toml/ini")
        self.configBrowseBtn = PushButton("Browse", self)
        self.configBrowseBtn.clicked.connect(self._on_browse_config)

        cfg_layout = QHBoxLayout()
        cfg_layout.addWidget(self.configPathInput)
        cfg_layout.addWidget(self.configBrowseBtn)

        self.remarksInput = LineEdit(self)
        self.remarksInput.setPlaceholderText("Remarks (optional)")

        if data:
            self.nameInput.setText(data.get("name", ""))
            self.exePathInput.setText(data.get("exe_path", ""))
            self.configPathInput.setText(data.get("config_path", ""))
            self.remarksInput.setText(data.get("remarks", ""))

        self.viewLayout.addWidget(self.titleLabel)
        form = QFormLayout()
        form.addRow("Name:", self.nameInput)
        form.addRow("Executable:", exe_layout)
        form.addRow("Config File:", cfg_layout)
        form.addRow("Remarks:", self.remarksInput)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(500)

    def _on_browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select frpc.exe", "", "Executable (*.exe);;All Files (*)"
        )
        if path:
            self.exePathInput.setText(path)

    def _on_browse_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select FRP Config", "", "Config Files (*.toml *.ini);;All Files (*)"
        )
        if path:
            self.configPathInput.setText(path)

    def get_data(self):
        return {
            "name": self.nameInput.text().strip(),
            "exe_path": self.exePathInput.text().strip(),
            "config_path": self.configPathInput.text().strip(),
            "remarks": self.remarksInput.text().strip(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["name"] and data["exe_path"] and data["config_path"])


class FRPManagerWidget(QWidget):
    """Main view for FRP Manager plugin."""

    def __init__(self, db, plugin, parent=None):
        super().__init__(parent)
        self.db = db
        self.plugin = plugin
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 20, 20, 20)
        self.mainLayout.setSpacing(15)

        # Header
        header = QHBoxLayout()
        self.titleLabel = BodyLabel("FRP Manager", self)
        self.titleLabel.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.addBtn = PushButton(FluentIcon.ADD, "Add FRP Config", self)
        self.addBtn.clicked.connect(self._on_add_clicked)

        from qfluentwidgets import SwitchButton

        self.sidebar_toggle = SwitchButton(self)
        self.sidebar_toggle.setOnText("Sidebar Status On")
        self.sidebar_toggle.setOffText("Sidebar Status Off")
        # Load initial state from plugin
        show_sidebar = self.plugin.context.state.get("show_sidebar_status", True)
        self.sidebar_toggle.setChecked(show_sidebar)
        self.sidebar_toggle.checkedChanged.connect(self._on_sidebar_toggle_changed)

        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(BodyLabel("Sidebar", self))
        header.addWidget(self.sidebar_toggle)
        header.addSpacing(20)
        header.addWidget(self.addBtn)
        self.mainLayout.addLayout(header)

        # Scroll Area
        self.scrollArea = BScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.flowLayout = FlowLayout(self.container)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setSpacing(15)

        self.scrollArea.setWidget(self.container)
        self.mainLayout.addWidget(self.scrollArea)

        self.refresh_list()

    def refresh_list(self):
        """Reload configs from DB and update UI."""
        self.flowLayout.takeAllWidgets()
        configs = self.db.fetchall("SELECT * FROM frp_configs ORDER BY created_at DESC")

        for cfg in configs:
            c_id = cfg["id"]
            name = cfg["name"]
            exe_path = cfg["exe_path"]
            config_path = cfg["config_path"]
            remarks = cfg["remarks"]
            is_running = self.plugin.is_running(c_id)

            tile = FRPConfigTile(
                c_id, name, exe_path, config_path, is_running, remarks, self.container
            )
            tile.start_requested.connect(self._on_start_requested)
            tile.stop_requested.connect(self._on_stop_requested)
            tile.edit_requested.connect(self._on_edit_clicked)
            tile.delete_requested.connect(self._on_delete_clicked)
            tile.edit_config_requested.connect(self._on_edit_config_requested)
            self.flowLayout.addWidget(tile)

    def _on_add_clicked(self):
        dialog = FRPConfigDialog(self.window())
        if dialog.exec():
            data = dialog.get_data()
            if dialog.validate():
                self.db.execute(
                    "INSERT INTO frp_configs (name, exe_path, config_path, remarks) VALUES (?, ?, ?, ?)",
                    (
                        data["name"],
                        data["exe_path"],
                        data["config_path"],
                        data["remarks"],
                    ),
                )
                self.refresh_list()
                InfoBar.success(
                    "Success",
                    "Configuration added",
                    duration=2000,
                    parent=self.window(),
                )
            else:
                InfoBar.error(
                    "Error",
                    "Required fields missing",
                    duration=2000,
                    parent=self.window(),
                )

    def _on_edit_clicked(self, config_id):
        cfg = self.db.fetchone("SELECT * FROM frp_configs WHERE id = ?", (config_id,))
        if not cfg:
            return

        dialog = FRPConfigDialog(self.window(), data=dict(cfg))
        if dialog.exec():
            data = dialog.get_data()
            if dialog.validate():
                self.db.execute(
                    "UPDATE frp_configs SET name=?, exe_path=?, config_path=?, remarks=? WHERE id=?",
                    (
                        data["name"],
                        data["exe_path"],
                        data["config_path"],
                        data["remarks"],
                        config_id,
                    ),
                )
                self.refresh_list()
                InfoBar.success(
                    "Success",
                    "Configuration updated",
                    duration=2000,
                    parent=self.window(),
                )

    def _on_delete_clicked(self, config_id):
        if self.plugin.is_running(config_id):
            InfoBar.warning(
                "Warning",
                "Stop the service before deleting",
                duration=2000,
                parent=self.window(),
            )
            return

        self.db.execute("DELETE FROM frp_configs WHERE id = ?", (config_id,))
        self.refresh_list()
        InfoBar.success(
            "Success", "Configuration deleted", duration=2000, parent=self.window()
        )

    def _on_start_requested(self, config_id):
        if self.plugin.start_frp(config_id):
            self.refresh_list()
            InfoBar.success(
                "Success", "FRP Service started", duration=2000, parent=self.window()
            )
        else:
            InfoBar.error(
                "Error",
                "Failed to start FRP Service",
                duration=3000,
                parent=self.window(),
            )

    def _on_stop_requested(self, config_id):
        if self.plugin.stop_frp(config_id):
            self.refresh_list()
            InfoBar.info(
                "Info", "FRP Service stopped", duration=2000, parent=self.window()
            )

    def _on_edit_config_requested(self, config_id):
        cfg = self.db.fetchone("SELECT * FROM frp_configs WHERE id = ?", (config_id,))
        if not cfg:
            return

        config_path = cfg["config_path"]
        if os.path.exists(config_path):
            try:
                os.startfile(config_path)
            except Exception as e:
                InfoBar.error(
                    "Error",
                    f"Failed to open config file: {e}",
                    duration=3000,
                    parent=self.window(),
                )
        else:
            InfoBar.error(
                "Error", "Config file not found", duration=3000, parent=self.window()
            )

    def _on_sidebar_toggle_changed(self, checked: bool):
        """Update plugin state and notify to refresh sidebar."""
        self.plugin.context.state.set("show_sidebar_status", checked)
        self.plugin._update_sidebar_status()


class FRPSidebarWidget(QWidget):
    """Compact sidebar widget showing FRP tunnel count."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._count = 0
        self._orientation = "vertical"
        self._init_ui()

    def _init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.layout.setAlignment(Qt.AlignCenter)

        self.label = StrongBodyLabel("FRP\n0", self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("font-size: 10px; color: #107c10;")
        self.layout.addWidget(self.label)

    def set_orientation(self, orientation: str):
        self._orientation = orientation
        self._update_display()

    def set_count(self, count: int):
        self._count = count
        self._update_display()

    def _update_display(self):
        if self._orientation == "top":
            self.label.setText(f"FRP: {self._count}")
        else:
            self.label.setText(f"FRP\n{self._count}")

        # Color based on whether any are running
        color = "#107c10" if self._count > 0 else "#666666"
        self.label.setStyleSheet(f"font-size: 10px; color: {color};")
