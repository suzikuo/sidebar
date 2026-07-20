from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from .views import ToolboxWidget


class ToolboxPlugin(PluginBase):
    """
    Toolbox plugin containing various utilities.
    """

    def __init__(self, context):
        super().__init__(context)
        self.ui_widget = None

    def on_load(self):
        logger.info("Toolbox plugin loading...")

    def on_unload(self):
        logger.info("Toolbox plugin unloading...")

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = ToolboxWidget()
            self.ui_widget.set_context(self.context)
        return self.ui_widget

    def get_icon(self):
        return FluentIcon.DEVELOPER_TOOLS

    def get_thumbnail_widget(self) -> QWidget:
        """Required by base class but not used in current sidebar"""
        from PySide6.QtWidgets import QPushButton

        btn = QPushButton("🧰")
        btn.setFixedSize(40, 40)
        btn.setFlat(True)
        btn.setStyleSheet(
            "QPushButton { color: white; font-size: 24px; background: transparent; border: none; }"
        )
        return btn
