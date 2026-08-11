"""Host-owned dialogs."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, PushButton


class PluginErrorDialog(QDialog):
    """Standalone error dialog for plugin loading failures."""

    def __init__(self, errors: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Load Errors")
        self.setMinimumWidth(450)
        self.setStyleSheet(
            """
            QDialog {
                background-color: #202020;
                border: 1px solid #3c3c3c;
                border-radius: 8px;
            }
            QLabel {
                color: white;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = BodyLabel("Plugin Load Errors", self)
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #006874;")
        layout.addWidget(title)

        details = "\n".join(f"\n- {plugin_id}:\n  {error}" for plugin_id, error in errors.items())
        content = BodyLabel(
            "The following plugins encountered errors during startup:\n" + details,
            self,
        )
        content.setWordWrap(True)
        layout.addWidget(content)
        layout.addStretch(1)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        self.ok_button = PushButton("Understood", self)
        self.ok_button.clicked.connect(self.accept)
        button_layout.addWidget(self.ok_button)
        layout.addLayout(button_layout)

        self._center_on_screen()

    def _center_on_screen(self):
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2,
        )
