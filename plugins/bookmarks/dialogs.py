from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import ComboBox, LineEdit, MessageBoxBase, SubtitleLabel, TextEdit


class AddBookmarkDialog(MessageBoxBase):
    """Dialog to add or edit a bookmark with notes and color"""

    def __init__(
        self, groups, parent=None, title="", url="", group_id=None, notes="", color=None
    ):
        super().__init__(parent)
        self.groups = groups
        self.titleLabel = SubtitleLabel("Add Bookmark", self)

        self.nameLineEdit = LineEdit(self)
        self.urlLineEdit = LineEdit(self)
        self.groupComboBox = ComboBox(self)
        self.notesTextEdit = TextEdit(self)
        self.colorComboBox = ComboBox(self)

        # Setup Groups
        for g in groups:
            self.groupComboBox.addItem(g["name"], userData=g["id"])

        if group_id is not None:
            for i in range(self.groupComboBox.count()):
                if self.groupComboBox.itemData(i) == group_id:
                    self.groupComboBox.setCurrentIndex(i)
                    break

        # Setup Colors
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

        if color:
            for i in range(self.colorComboBox.count()):
                if self.colorComboBox.itemData(i) == color:
                    self.colorComboBox.setCurrentIndex(i)
                    break

        self.nameLineEdit.setPlaceholderText("Enter site name (e.g. Google)")
        self.urlLineEdit.setPlaceholderText("Enter URL (e.g. https://google.com)")
        self.notesTextEdit.setPlaceholderText("Additional notes...")
        self.notesTextEdit.setFixedHeight(80)

        self.nameLineEdit.setText(title)
        self.urlLineEdit.setText(url)
        self.notesTextEdit.setMarkdown(notes)

        self.nameLineEdit.setClearButtonEnabled(True)
        self.urlLineEdit.setClearButtonEnabled(True)

        # Add widgets to layout
        self.viewLayout.addWidget(self.titleLabel)

        formLayout = QFormLayout()
        formLayout.setContentsMargins(0, 10, 0, 10)
        formLayout.addRow("Name:", self.nameLineEdit)
        formLayout.addRow("URL:", self.urlLineEdit)
        formLayout.addRow("Group:", self.groupComboBox)
        formLayout.addRow("Color:", self.colorComboBox)
        formLayout.addRow("Notes:", self.notesTextEdit)

        self.viewLayout.addLayout(formLayout)

        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")

        self.widget.setMinimumWidth(400)

    def get_data(self):
        return {
            "title": self.nameLineEdit.text().strip(),
            "url": self.urlLineEdit.text().strip(),
            "group_id": self.groupComboBox.currentData(),
            "notes": self.notesTextEdit.toPlainText().strip(),
            "color": self.colorComboBox.currentData(),
        }

    def validate(self):
        data = self.get_data()
        return bool(data["title"] and data["url"])


class AddGroupDialog(MessageBoxBase):
    """Dialog to add a new group"""

    def __init__(self, parent=None, name="", color=None):
        super().__init__(parent)
        title = "Edit Group" if name else "Add Group"
        self.titleLabel = SubtitleLabel(title, self)
        self.nameLineEdit = LineEdit(self)
        self.nameLineEdit.setPlaceholderText("Enter group name (e.g. Work)")
        self.nameLineEdit.setText(name)
        self.colorComboBox = ComboBox(self)

        # Setup Colors
        colors = [
            ("Default", None),
            ("Blue", "#0078d4"),
            ("Green", "#107c10"),
            ("Red", "#d13438"),
            ("Purple", "#5c2d91"),
            ("Orange", "#d83b01"),
        ]
        for cname, hex_val in colors:
            self.colorComboBox.addItem(cname, userData=hex_val)

        if color:
            for i in range(self.colorComboBox.count()):
                if self.colorComboBox.itemData(i) == color:
                    self.colorComboBox.setCurrentIndex(i)
                    break

        self.viewLayout.addWidget(self.titleLabel)

        formLayout = QFormLayout()
        formLayout.setContentsMargins(0, 10, 0, 10)
        formLayout.addRow("Name:", self.nameLineEdit)
        formLayout.addRow("Color:", self.colorComboBox)

        self.viewLayout.addLayout(formLayout)

        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")
        self.widget.setMinimumWidth(300)

    def get_data(self):
        return {
            "name": self.nameLineEdit.text().strip(),
            "color": self.colorComboBox.currentData(),
        }

    def validate(self):
        return bool(self.nameLineEdit.text().strip())
