from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.plugin_system.plugin_base import PluginBase


class WindowsControlsPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.description = "音量、亮度、电源与快捷设置"
        self._widget = None
        self._controller = None

    def on_load(self):
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
        if self._controller is not None:
            self._controller.deleteLater()
            self._controller = None
        if self._widget is not None:
            self._widget.close()
            self._widget.deleteLater()
            self._widget = None

    def get_icon(self):
        return FluentIcon.SETTING

    def get_thumbnail_widget(self):
        return None

    def get_card_widget(self) -> QWidget:
        if self._widget is None:
            from .controller import WindowsControlController
            from .views import WindowsControlsWidget

            self._widget = WindowsControlsWidget()
            self._controller = WindowsControlController(
                self.context,
                parent=self._widget,
            )
            self._widget.refresh_requested.connect(self._controller.refresh)
            self._widget.action_requested.connect(self._controller.perform)
            self._controller.snapshot_ready.connect(self._widget.apply_snapshot)
            self._controller.action_finished.connect(self._widget.show_completed)
            self._controller.error.connect(self._widget.show_error)
        return self._widget

    def _command_catalog(self, payload, request_context):
        del payload, request_context
        return {
            "commands": [
                {
                    "id": "open",
                    "name": "打开 Windows 控制",
                    "subtitle": "音量、亮度、电源与快捷设置",
                    "category": "系统",
                    "route": "command-execute",
                    "payload": {},
                }
            ]
        }

    def _command_execute(self, payload, request_context):
        del payload, request_context
        self.context.open_detail_view()
        return {"executed": True}


__all__ = ["WindowsControlsPlugin"]
