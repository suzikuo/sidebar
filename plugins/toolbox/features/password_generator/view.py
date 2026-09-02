from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    Slider,
    StrongBodyLabel,
    SwitchButton,
    TitleLabel,
)

from .logic import PasswordGenerator


class PasswordGeneratorWidget(QWidget):
    """
    Widget for generating secure passwords.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.generator = PasswordGenerator()

        self.vLayout = QVBoxLayout(self)
        self.vLayout.setContentsMargins(30, 30, 30, 30)
        self.vLayout.setSpacing(20)

        # Generator Display Area
        self.displayCard = CardWidget(self)
        self.displayLayout = QHBoxLayout(self.displayCard)
        self.displayLayout.setContentsMargins(20, 20, 20, 20)

        self.passwordLabel = TitleLabel("Generating...", self)
        self.passwordLabel.setAlignment(Qt.AlignCenter)
        # Make it selectable/copyable easily
        self.passwordLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Use a monospaced font if possible, or just large text
        font = self.passwordLabel.font()
        font.setPointSize(24)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2)
        self.passwordLabel.setFont(font)

        self.displayLayout.addWidget(self.passwordLabel)

        self.vLayout.addWidget(self.displayCard)

        # Actions
        self.actionLayout = QHBoxLayout()

        self.copyBtn = PrimaryPushButton(FluentIcon.COPY, "Copy", self)
        self.copyBtn.clicked.connect(self._copy_password)
        self.copyBtn.setFixedWidth(150)

        self.refreshBtn = PushButton(FluentIcon.SYNC, "Regenerate", self)
        self.refreshBtn.clicked.connect(self._generate)
        self.refreshBtn.setFixedWidth(150)

        self.actionLayout.addStretch(1)
        self.actionLayout.addWidget(self.copyBtn)
        self.actionLayout.addWidget(self.refreshBtn)
        self.actionLayout.addStretch(1)

        self.vLayout.addLayout(self.actionLayout)

        # Settings
        self.settingsCard = CardWidget(self)
        self.settingsLayout = QVBoxLayout(self.settingsCard)
        self.settingsLayout.setContentsMargins(20, 20, 20, 20)

        self.settingsLayout.addWidget(StrongBodyLabel("Configuration", self))

        # Length
        self.lengthLayout = QHBoxLayout()
        self.lengthLabel = StrongBodyLabel("Length: 16", self)
        self.lengthSlider = Slider(Qt.Horizontal, self)
        self.lengthSlider.setRange(8, 64)
        self.lengthSlider.setValue(16)
        self.lengthSlider.valueChanged.connect(self._update_length_label)
        self.lengthSlider.valueChanged.connect(self._generate)

        self.lengthLayout.addWidget(self.lengthLabel)
        self.lengthLayout.addSpacing(10)
        self.lengthLayout.addWidget(self.lengthSlider)
        self.settingsLayout.addLayout(self.lengthLayout)

        self.settingsLayout.addSpacing(10)

        # Toggles
        self.togglesLayout = QHBoxLayout()
        self.togglesLayout.setSpacing(20)

        self.digitsSwitch = SwitchButton("Numbers (0-9)")
        self.digitsSwitch.setChecked(True)
        self.digitsSwitch.checkedChanged.connect(self._generate)

        self.symbolsSwitch = SwitchButton("Symbols (!@#$)")
        self.symbolsSwitch.setChecked(True)
        self.symbolsSwitch.checkedChanged.connect(self._generate)

        self.togglesLayout.addWidget(self.digitsSwitch)
        self.togglesLayout.addWidget(self.symbolsSwitch)
        self.togglesLayout.addStretch(1)

        self.settingsLayout.addLayout(self.togglesLayout)

        self.vLayout.addWidget(self.settingsCard)
        self.vLayout.addStretch(1)

        # Initial generation
        self._generate()

    def _update_length_label(self, value):
        self.lengthLabel.setText(f"Length: {value}")

    def _generate(self):
        length = self.lengthSlider.value()
        use_digits = self.digitsSwitch.isChecked()
        use_symbols = self.symbolsSwitch.isChecked()

        pwd = self.generator.generate(
            length=length, use_digits=use_digits, use_symbols=use_symbols
        )
        self.passwordLabel.setText(pwd)

    def _copy_password(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.passwordLabel.text())

        InfoBar.success(
            title="Copied",
            content="Password copied to clipboard.",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self,
        )
