import shutil
from pathlib import Path

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
    CheckBox,
    ComboBox,
    FlowLayout,
    FluentIcon,
    IconWidget,
    InfoBar,
    LineEdit,
    MessageBoxBase,
    PushButton,
    RadioButton,
    RoundMenu,
    SpinBox,
    SubtitleLabel,
    TextEdit,
    TransparentToolButton,
)

from ui.components.base_widget import BScrollArea


class SSHConnectionTile(CardWidget):
    """A tile representing an SSH connection."""

    connect_requested = Signal(int)
    edit_requested = Signal(int)
    delete_requested = Signal(int)
    scp_requested = Signal(int)

    def __init__(
        self, conn_id, name, host, user, port, remarks="", color=None, parent=None
    ):
        super().__init__(parent)
        self.conn_id = conn_id
        self.setFixedSize(220, 140)
        self.setCursor(Qt.PointingHandCursor)

        self.mainLayout = QHBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        # Color Bar
        if color:
            self.colorBar = QWidget(self)
            self.colorBar.setFixedWidth(5)
            self.colorBar.setStyleSheet(
                f"background-color: {color}; border-top-left-radius: 8px; border-bottom-left-radius: 8px;"
            )
            self.mainLayout.addWidget(self.colorBar)
        else:
            # Add a small placeholder even if no color to keep alignment consistent
            self.colorBar = QWidget(self)
            self.colorBar.setFixedWidth(2)
            self.colorBar.setStyleSheet("background-color: transparent;")
            self.mainLayout.addWidget(self.colorBar)

        # Content Container
        self.contentWidget = QWidget(self)
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setContentsMargins(15, 12, 15, 12)
        self.contentLayout.setSpacing(4)
        self.mainLayout.addWidget(self.contentWidget)

        # Header: Icon + Name
        header_layout = QHBoxLayout()
        icon = IconWidget(FluentIcon.COMMAND_PROMPT, self)
        icon.setFixedSize(20, 20)

        name_label = BodyLabel(name, self)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        header_layout.addWidget(icon)
        header_layout.addWidget(name_label)
        header_layout.addStretch(1)
        self.contentLayout.addLayout(header_layout)

        # Details
        info_label = CaptionLabel(f"{user}@{host}:{port}", self)
        info_label.setStyleSheet("color: rgba(255, 255, 255, 0.6);")
        self.contentLayout.addWidget(info_label)

        if remarks:
            remarks_label = CaptionLabel(remarks, self)
            remarks_label.setStyleSheet(
                "color: rgba(255, 255, 255, 0.4); font-style: italic;"
            )
            remarks_label.setWordWrap(True)
            self.contentLayout.addWidget(remarks_label)

        self.contentLayout.addStretch(1)

        # Connect Button (Bottom Right)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.connect_btn = TransparentToolButton(FluentIcon.SEND, self)
        self.connect_btn.setToolTip("Connect")
        self.connect_btn.clicked.connect(
            lambda: self.connect_requested.emit(self.conn_id)
        )
        btn_layout.addWidget(self.connect_btn)
        self.contentLayout.addLayout(btn_layout)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton:
            # Maybe just open detail or connect? User said "ssh使用windows的命令行 执行ssh命令链接"
            # So clicking should probably connect.
            self.connect_requested.emit(self.conn_id)

    def contextMenuEvent(self, e):
        menu = RoundMenu(parent=self)
        scp_action = Action(FluentIcon.MOVE, "SCP Transfer", self)
        edit_action = Action(FluentIcon.EDIT, "Edit", self)
        delete_action = Action(FluentIcon.DELETE, "Delete", self)

        scp_action.triggered.connect(lambda: self.scp_requested.emit(self.conn_id))
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self.conn_id))
        delete_action.triggered.connect(
            lambda: self.delete_requested.emit(self.conn_id)
        )

        menu.addAction(scp_action)
        menu.addSeparator()
        menu.addAction(edit_action)
        menu.addAction(delete_action)
        menu.exec(e.globalPos())


class SCPTransferDialog(MessageBoxBase):
    """Dialog to configure an SCP file transfer."""

    def __init__(self, parent=None, conn_name=""):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel(f"SCP Transfer - {conn_name}", self)

        # Direction
        self.uploadRadio = RadioButton("Upload to Remote", self)
        self.downloadRadio = RadioButton("Download to Local", self)
        self.uploadRadio.setChecked(True)

        dir_layout = QHBoxLayout()
        dir_layout.addWidget(self.uploadRadio)
        dir_layout.addWidget(self.downloadRadio)

        self.uploadRadio.toggled.connect(self._update_placeholders)
        self.downloadRadio.toggled.connect(self._update_placeholders)

        # Local Path
        self.localPathInput = LineEdit(self)
        self.localPathInput.setPlaceholderText("Local file or folder path")
        self.localBrowseBtn = PushButton("Browse", self)
        self.localBrowseBtn.clicked.connect(self._on_browse_local)

        local_layout = QHBoxLayout()
        local_layout.addWidget(self.localPathInput)
        local_layout.addWidget(self.localBrowseBtn)

        # Remote Path
        self.remotePathInput = LineEdit(self)
        self.remotePathInput.setPlaceholderText(
            "Remote destination path (e.g. /home/root/)"
        )

        # Recursive
        self.recursiveCheck = CheckBox("Recursive (for folders)", self)
        self.recursiveCheck.setChecked(False)
        self.recursiveCheck.toggled.connect(self._update_placeholders)

        # Layout
        self.viewLayout.addWidget(self.titleLabel)
        form = QFormLayout()
        form.addRow("Direction:", dir_layout)
        form.addRow("Local Path:", local_layout)
        form.addRow("Remote Path:", self.remotePathInput)
        form.addRow("", self.recursiveCheck)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Transfer")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(500)
        self._update_placeholders()

    def _update_placeholders(self):
        if self.downloadRadio.isChecked():
            self.localPathInput.setPlaceholderText("Local destination directory")
            self.remotePathInput.setPlaceholderText("Remote file or folder path")
        else:
            self.localPathInput.setPlaceholderText("Local file or folder path")
            self.remotePathInput.setPlaceholderText("Remote destination directory")

    def _on_browse_local(self):
        if self.downloadRadio.isChecked():
            # Download always chooses a destination directory
            path = QFileDialog.getExistingDirectory(
                self, "Select Local Destination Directory"
            )
        elif self.recursiveCheck.isChecked():
            # Upload folder
            path = QFileDialog.getExistingDirectory(
                self, "Select Local Source Directory"
            )
        else:
            # Upload file
            path, _ = QFileDialog.getOpenFileName(self, "Select Local Source File")

        if path:
            self.localPathInput.setText(path)

    def get_data(self):
        return {
            "mode": "upload" if self.uploadRadio.isChecked() else "download",
            "local_path": self.localPathInput.text().strip(),
            "remote_path": self.remotePathInput.text().strip(),
            "recursive": self.recursiveCheck.isChecked(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["local_path"] and data["remote_path"])


class SSHConnectionDialog(MessageBoxBase):
    """Dialog to add or edit an SSH connection."""

    def __init__(self, parent=None, data=None, keys_dir=None):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel("SSH Connection Settings", self)

        # Path for backing up keys - passed from plugin/widget
        self._keys_dir = Path(keys_dir) if keys_dir else Path(__file__).parent / "keys"
        if not self._keys_dir.exists():
            self._keys_dir.mkdir(parents=True, exist_ok=True)

        self.nameInput = LineEdit(self)
        self.hostInput = LineEdit(self)
        self.userInput = LineEdit(self)
        self.portInput = SpinBox(self)
        self.portInput.setRange(1, 65535)
        self.portInput.setValue(22)
        self.pemPathInput = LineEdit(self)
        self.remarksInput = TextEdit(self)
        self.remarksInput.setFixedHeight(120)  # Made larger
        self.colorComboBox = ComboBox(self)

        # Setup Colors (Same as Bookmarks plugin)
        colors = [
            ("Default", None),
            ("Blue", "#0078d4"),
            ("Green", "#107c10"),
            ("Red", "#d13438"),
            ("Purple", "#5c2d91"),
            ("Orange", "#d83b01"),
        ]
        for name, hex_val in colors:
            self.colorComboBox.addItem(name, userData=hex_val)

        # Keys Dropdown Button
        self.keysBtn = TransparentToolButton(FluentIcon.HISTORY, self)
        self.keysBtn.setToolTip("Select from existing keys")
        self.keysBtn.clicked.connect(self._show_keys_menu)

        # Pem Browse Button
        self.browseBtn = PushButton("Browse", self)
        self.browseBtn.clicked.connect(self._on_browse_pem)

        pem_layout = QHBoxLayout()
        pem_layout.addWidget(self.pemPathInput)
        pem_layout.addWidget(self.keysBtn)
        pem_layout.addWidget(self.browseBtn)

        # Set Placeholders
        self.nameInput.setPlaceholderText("Connection Name (e.g. Production)")
        self.hostInput.setPlaceholderText("IP or Hostname")
        self.userInput.setPlaceholderText("Username (default: root)")
        self.pemPathInput.setPlaceholderText("Path to .pem file (optional)")
        self.remarksInput.setPlaceholderText("Remarks...")

        # Fill data if editing
        if data:
            self.nameInput.setText(data.get("name", ""))
            self.hostInput.setText(data.get("host", ""))
            self.userInput.setText(data.get("user", "root"))
            self.portInput.setValue(data.get("port", 22))
            self.pemPathInput.setText(data.get("pem_path", ""))
            self.remarksInput.setMarkdown(data.get("remarks", ""))

            color = data.get("color")
            if color:
                for i in range(self.colorComboBox.count()):
                    if self.colorComboBox.itemData(i) == color:
                        self.colorComboBox.setCurrentIndex(i)
                        break

        # Layout
        self.viewLayout.addWidget(self.titleLabel)
        form = QFormLayout()
        form.addRow("Name:", self.nameInput)
        form.addRow("Host:", self.hostInput)
        form.addRow("User:", self.userInput)
        form.addRow("Port:", self.portInput)
        form.addRow("PEM Path:", pem_layout)
        form.addRow("Color:", self.colorComboBox)
        form.addRow("Remarks:", self.remarksInput)
        self.viewLayout.addLayout(form)

        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(450)

    def _show_keys_menu(self):
        """Show a menu with files in the keys directory."""
        if not self._keys_dir.exists():
            return

        files = list(self._keys_dir.glob("*"))
        if not files:
            InfoBar.info(
                "Info",
                "No keys found in local storage",
                duration=2000,
                parent=self.window(),
            )
            return

        menu = RoundMenu(parent=self)
        for f in files:
            if f.is_file():
                # Use a specific icon for keys if possible, or just COMMAND_PROMPT
                action = Action(FluentIcon.CERTIFICATE, f.name, self)
                action.triggered.connect(
                    lambda checked=False, name=f.name: self.pemPathInput.setText(name)
                )
                menu.addAction(action)

        # Position menu below the button
        menu.exec(self.keysBtn.mapToGlobal(self.keysBtn.rect().bottomLeft()))

    def _on_browse_pem(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select PEM File", "", "PrivateKey Files (*.pem *.ppk);;All Files (*)"
        )
        if file_path:
            # Copy to local keys directory
            src = Path(file_path)
            dest = self._keys_dir / src.name

            try:
                if src.absolute() != dest.absolute():
                    shutil.copy2(src, dest)
                self.pemPathInput.setText(dest.name)
                InfoBar.success(
                    "Backup",
                    f"Key backed up to {dest.name}",
                    duration=2000,
                    parent=self.window(),
                )
            except Exception as e:
                InfoBar.error(
                    "Backup Failed", str(e), duration=3000, parent=self.window()
                )
                self.pemPathInput.setText(file_path)

    def get_data(self):
        return {
            "name": self.nameInput.text().strip(),
            "host": self.hostInput.text().strip(),
            "user": self.userInput.text().strip() or "root",
            "port": self.portInput.value(),
            "pem_path": self.pemPathInput.text().strip(),
            "remarks": self.remarksInput.toPlainText().strip(),
            "color": self.colorComboBox.currentData(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["name"] and data["host"])


class SSHManagerWidget(QWidget):
    """Main view for SSH Manager plugin."""

    connect_requested = Signal(int)
    scp_requested = Signal(int, dict)

    def __init__(self, db, keys_dir, parent=None):
        super().__init__(parent)
        self.db = db
        self.keys_dir = keys_dir
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 20, 20, 20)
        self.mainLayout.setSpacing(15)

        # Header
        header = QHBoxLayout()
        self.titleLabel = BodyLabel("SSH Manager", self)
        self.titleLabel.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.addBtn = PushButton(FluentIcon.ADD, "Add Connection", self)
        self.addBtn.clicked.connect(self._on_add_clicked)

        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.addBtn)
        self.mainLayout.addLayout(header)

        # Scroll Area for Flow Layout
        self.scrollArea = BScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.flowLayout = FlowLayout(self.container)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setSpacing(15)

        self.scrollArea.setWidget(self.container)
        self.mainLayout.addWidget(self.scrollArea)

        self._refresh_list()

    def _refresh_list(self):
        """Reload connections from DB and update UI."""
        self.flowLayout.takeAllWidgets()

        conns = self.db.fetchall(
            "SELECT * FROM ssh_connections ORDER BY created_at DESC"
        )

        for conn in conns:
            # Use name-based access which is much safer across migrations
            c_id = conn["id"]
            name = conn["name"]
            host = conn["host"]
            user = conn["user"]
            port = conn["port"]
            remarks = conn["remarks"]

            # Safely handle color which might be missing in very old Row or if migration had issues
            try:
                color = conn["color"]
            except (IndexError, KeyError):
                color = None

            tile = SSHConnectionTile(
                c_id, name, host, user, port, remarks, color, self.container
            )
            tile.connect_requested.connect(self.connect_requested.emit)
            tile.scp_requested.connect(self._on_scp_clicked)
            tile.edit_requested.connect(self._on_edit_clicked)
            tile.delete_requested.connect(self._on_delete_clicked)
            self.flowLayout.addWidget(tile)

    def _on_add_clicked(self):
        dialog = SSHConnectionDialog(self.window(), keys_dir=self.keys_dir)
        if dialog.exec():
            data = dialog.get_data()
            if dialog.validate():
                self.db.execute(
                    """
                    INSERT INTO ssh_connections (name, host, user, port, pem_path, remarks, color)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        data["name"],
                        data["host"],
                        data["user"],
                        data["port"],
                        data["pem_path"],
                        data["remarks"],
                        data["color"],
                    ),
                )
                self._refresh_list()
                InfoBar.success(
                    "Success", "Connection added", duration=2000, parent=self.window()
                )
            else:
                InfoBar.error(
                    "Error",
                    "Name and Host are required",
                    duration=2000,
                    parent=self.window(),
                )

    def _on_scp_clicked(self, conn_id):
        conn = self.db.fetchone(
            "SELECT * FROM ssh_connections WHERE id = ?", (conn_id,)
        )
        if not conn:
            return

        conn_name = conn["name"] if isinstance(conn, dict) else conn[1]
        dialog = SCPTransferDialog(self.window(), conn_name=conn_name)
        if dialog.exec():
            data = dialog.get_data()
            if dialog.validate():
                self.scp_requested.emit(conn_id, data)
            else:
                InfoBar.error(
                    "Error",
                    "Required fields missing",
                    duration=2000,
                    parent=self.window(),
                )

    def _on_edit_clicked(self, conn_id):
        conn = self.db.fetchone(
            "SELECT * FROM ssh_connections WHERE id = ?", (conn_id,)
        )
        if not conn:
            return

        if isinstance(conn, dict):
            data = dict(conn)  # Ensure it's a mutable dict for safety
        else:
            # Based on updated schema: id=0, name=1, host=2, user=3, port=4, pem=5, remarks=6, color=7
            data = {
                "name": conn[1],
                "host": conn[2],
                "user": conn[3],
                "port": conn[4],
                "pem_path": conn[5],
                "remarks": conn[6],
                "color": conn[7] if len(conn) > 7 else None,
            }

        dialog = SSHConnectionDialog(self.window(), data=data, keys_dir=self.keys_dir)
        if dialog.exec():
            new_data = dialog.get_data()
            if dialog.validate():
                self.db.execute(
                    """
                    UPDATE ssh_connections 
                    SET name=?, host=?, user=?, port=?, pem_path=?, remarks=?, color=?
                    WHERE id=?
                    """,
                    (
                        new_data["name"],
                        new_data["host"],
                        new_data["user"],
                        new_data["port"],
                        new_data["pem_path"],
                        new_data["remarks"],
                        new_data["color"],
                        conn_id,
                    ),
                )
                self._refresh_list()
                InfoBar.success(
                    "Success", "Connection updated", duration=2000, parent=self.window()
                )

    def _on_delete_clicked(self, conn_id):
        # Could add a confirmation dialog here
        self.db.execute("DELETE FROM ssh_connections WHERE id = ?", (conn_id,))
        self._refresh_list()
        InfoBar.success(
            "Success", "Connection deleted", duration=2000, parent=self.window()
        )
