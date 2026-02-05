from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FlowLayout,
    IconWidget,
    SearchLineEdit,
)

from ui.components.base_widget import BScrollArea

from .features.base import ToolboxFeature


class ToolCard(CardWidget):
    """
    A card representing a tool in the dashboard, matching the SSH Manager style.
    """

    clicked = Signal()

    def __init__(self, feature: ToolboxFeature, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 140)
        self.setCursor(Qt.PointingHandCursor)
        self.feature = feature

        self.mainLayout = QHBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)

        # Content Container
        self.contentWidget = QWidget(self)
        self.contentLayout = QVBoxLayout(self.contentWidget)
        self.contentLayout.setContentsMargins(15, 12, 15, 12)
        self.contentLayout.setSpacing(4)
        self.mainLayout.addWidget(self.contentWidget)

        # Header: Icon + Name
        header_layout = QHBoxLayout()
        icon = IconWidget(feature.icon, self)
        icon.setFixedSize(20, 20)

        name_label = BodyLabel(feature.name, self)
        name_label.setStyleSheet("font-weight: bold; font-size: 14px;")

        header_layout.addWidget(icon)
        header_layout.addWidget(name_label)
        header_layout.addStretch(1)
        self.contentLayout.addLayout(header_layout)

        # Description
        desc_label = CaptionLabel(feature.description, self)
        desc_label.setStyleSheet("color: rgba(255, 255, 255, 0.6);")
        desc_label.setWordWrap(True)
        self.contentLayout.addWidget(desc_label)

        self.contentLayout.addStretch(1)

        # Launch Button (Bottom Right)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        # self.launch_btn = TransparentToolButton(FluentIcon.SEND, self)
        # self.launch_btn.setToolTip("Launch Tool")
        # self.launch_btn.clicked.connect(self.clicked.emit)
        # btn_layout.addWidget(self.launch_btn)
        self.contentLayout.addLayout(btn_layout)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit()


class ToolWindow(QWidget):
    """
    Wrapper window for a tool.
    """

    def __init__(self, title, widget, parent=None):
        super().__init__()  # No parent to be a separate window
        self.setWindowTitle(title)
        self.resize(600, 600)

        self.vLayout = QVBoxLayout(self)
        self.vLayout.setContentsMargins(0, 0, 0, 0)
        self.vLayout.addWidget(widget)

        # Keep reference to widget
        self.widget = widget


class ToolboxWidget(QWidget):
    """
    Dashboard for Toolbox utilities, matching the SSH Manager style.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(20, 20, 20, 20)
        self.mainLayout.setSpacing(15)

        # Header
        header = QHBoxLayout()
        self.titleLabel = BodyLabel("Toolbox", self)
        self.titleLabel.setStyleSheet("font-size: 24px; font-weight: bold;")

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("Search tools...")
        self.searchEdit.setFixedWidth(250)
        self.searchEdit.textChanged.connect(self._on_search_changed)

        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(self.searchEdit)
        self.mainLayout.addLayout(header)

        # Scroll Area for Flow Layout
        self.scrollArea = BScrollArea(self)
        self.scrollArea.setWidgetResizable(True)

        self.container = QWidget()
        self.container.setStyleSheet("background: transparent;")
        self.flowLayout = FlowLayout(self.container, needAni=True)
        self.flowLayout.setContentsMargins(0, 0, 0, 0)
        self.flowLayout.setSpacing(15)

        self.scrollArea.setWidget(self.container)
        self.mainLayout.addWidget(self.scrollArea)

        # Keep track of open windows to prevent GC
        self._open_windows = []
        self._cards = []

        self._load_tools()

    def _load_tools(self):
        """Dynamically discover and load tools from the features directory."""
        import importlib
        import os
        import sys
        from pathlib import Path

        features_dir = Path(__file__).parent / "features"

        if str(features_dir) not in sys.path:
            sys.path.append(str(features_dir))

        for entry in os.scandir(features_dir):
            if entry.is_dir() and (features_dir / entry.name / "tool.py").exists():
                try:
                    module_name = f"plugins.toolbox.features.{entry.name}.tool"
                    if module_name in sys.modules:
                        module = sys.modules[module_name]
                    else:
                        module = importlib.import_module(module_name)

                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, ToolboxFeature)
                            and attr is not ToolboxFeature
                        ):
                            feature = attr()
                            self._add_tool_card(feature)
                            break

                except Exception as e:
                    print(f"[Toolbox] Failed to load tool '{entry.name}': {e}")

    def _add_tool_card(self, feature: ToolboxFeature):
        card = ToolCard(feature, self.container)
        card.clicked.connect(lambda f=feature: self._open_tool(f))
        self.flowLayout.addWidget(card)
        self._cards.append(card)

    def _on_search_changed(self, text):
        text = text.lower()
        for card in self._cards:
            visible = (
                text in card.feature.name.lower()
                or text in card.feature.description.lower()
            )
            card.setVisible(visible)

    def _open_tool(self, feature: ToolboxFeature):
        # Check if already open
        for win in self._open_windows:
            if win.windowTitle() == feature.name:
                win.show()
                win.activateWindow()
                if win.isMinimized():
                    win.showNormal()
                return

        try:
            tool_widget = feature.create_widget()
            window = ToolWindow(feature.name, tool_widget)
            window.show()

            self._open_windows.append(window)
            window.setAttribute(Qt.WA_DeleteOnClose)
            window.destroyed.connect(
                lambda: self._open_windows.remove(window)
                if window in self._open_windows
                else None
            )

        except Exception as e:
            print(f"[Toolbox] Error opening {feature.name}: {e}")
