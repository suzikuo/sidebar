from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase


class ToolboxPlugin(PluginBase):
    """
    Toolbox plugin containing various utilities.
    """

    def __init__(self, context):
        super().__init__(context)
        self.ui_widget = None

    def on_load(self):
        logger.info("Toolbox plugin loading...")
        self.context.register_api_route(
            "command-catalog",
            self._command_catalog,
            exported_capability="command.catalog",
        )
        self.context.register_api_route(
            "command-execute",
            self._command_execute,
            exported_capability="command.execute",
        )

    def on_unload(self):
        logger.info("Toolbox plugin unloading...")

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            from .views import ToolboxWidget

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

    def _command_catalog(self, payload, request_context):
        del payload, request_context
        return {
            "commands": [
                {
                    "id": "open",
                    "name": "打开工具箱",
                    "subtitle": "密码、图片、Hosts 与端口工具",
                    "category": "工具箱",
                    "route": "command-execute",
                    "payload": {},
                }
            ]
        }

    def _command_execute(self, payload, request_context):
        del payload, request_context
        self.context.open_detail_view()
        return {"executed": True}
