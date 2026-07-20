from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    InfoBar,
    InfoBarPosition,
    PlainTextEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
)

from .logic import HostFileHandler


class HostModifierWidget(QWidget):
    """
    Widget for viewing and editing the hosts file.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.handler = HostFileHandler()

        self.vLayout = QVBoxLayout(self)
        self.vLayout.setContentsMargins(16, 16, 16, 16)
        self.vLayout.setSpacing(16)

        # Header
        self.headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Host File Editor", self)

        self.loadBtn = PushButton("Load Content", self)
        self.loadBtn.clicked.connect(self._load_hosts)

        self.saveBtn = PrimaryPushButton("Save Changes", self)
        self.saveBtn.clicked.connect(self._save_changes)

        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)
        self.headerLayout.addWidget(self.loadBtn)
        self.headerLayout.addWidget(self.saveBtn)
        self.vLayout.addLayout(self.headerLayout)

        # Editor
        self.editor = PlainTextEdit(self)
        self.editor.setPlaceholderText("Click 'Load Content' to view hosts file.")
        self.vLayout.addWidget(self.editor)

        # Do not load content automatically
        # self._load_hosts()

    def _load_hosts(self):
        content = self.handler.read_hosts()
        self.editor.setPlainText(content)

        if not self.handler.is_writable():
            InfoBar.info(
                title="Elevation Required",
                content="Saving changes will require Administrator privileges (UAC).",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )

    def _save_changes(self):
        content = self.editor.toPlainText()
        success = self.handler.write_hosts(content)

        if success:
            InfoBar.success(
                title="Success",
                content="Hosts file update requested. Please accept the UAC prompt if it appears.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
        else:
            InfoBar.error(
                title="Failed",
                content="Could not write to hosts file.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self,
            )
