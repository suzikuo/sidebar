from typing import Any, Dict

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel

from core.logger import logger
from core.ui_kernel.theme_engine import ThemeEngine
from core.ui_kernel.view_host.card_lifecycle import CardLifecycle
from ui.components.base_widget import BaseWidget


class PluginCard(BaseWidget, CardLifecycle):
    """
    The visual container for a plugin instance within the sidebar.
    """

    def __init__(self, plugin_name: str, theme_engine: ThemeEngine, parent=None):
        super().__init__(theme_engine, parent)
        self.setObjectName("PluginCard")
        self.layout = QVBoxLayout(self)

        self.header = BodyLabel(plugin_name)
        self.header.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.layout.addWidget(self.header)

        self.content_area = QFrame()
        self.layout.addWidget(self.content_area)

        self.apply_style()

    def apply_style(self):
        self.setStyleSheet(self.theme_engine.get_component_qss("PluginCard"))

    def set_content(self, widget: QWidget):
        if self.content_area.layout():
            # Clear existing
            while self.content_area.layout().count():
                child = self.content_area.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
        else:
            self.content_area.setLayout(QVBoxLayout())

        self.content_area.layout().addWidget(widget)

    # CardLifecycle Implementation
    def on_show(self):
        logger.debug(f"PluginCard '{self.header.text()}' is now visible.")

    def on_hide(self):
        logger.debug(f"PluginCard '{self.header.text()}' is now hidden.")

    def save_state(self) -> Dict[str, Any]:
        return {"title": self.header.text()}

    def restore_state(self, state: Dict[str, Any]):
        if "title" in state:
            self.header.setText(state["title"])
