from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.plugin_system.plugin_base import PluginBase


class PluginDiagnosticsPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.description = "宿主资源、插件模块与错误日志"
        self._widget = None
        self._service = None

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
        if self._service is not None:
            self._service.stop()
            self._service.deleteLater()
            self._service = None
        if self._widget is not None:
            self._widget.close()
            self._widget.deleteLater()
            self._widget = None

    def get_icon(self):
        return FluentIcon.INFO

    def get_thumbnail_widget(self):
        return None

    def get_card_widget(self) -> QWidget:
        if self._widget is None:
            from .service import DiagnosticService
            from .views import PluginDiagnosticsWidget

            self._widget = PluginDiagnosticsWidget()
            self._service = DiagnosticService(self.context, parent=self._widget)
            self._widget.active_changed.connect(self._set_active)
            self._widget.refresh_requested.connect(self._service.refresh)
            self._service.snapshot_ready.connect(self._widget.apply_snapshot)
            self._service.error.connect(self._widget.show_error)
        return self._widget

    def _set_active(self, active):
        if active:
            self._service.start()
        else:
            self._service.stop()

    def _command_catalog(self, payload, request_context):
        del payload, request_context
        return {
            "commands": [
                {
                    "id": "open",
                    "name": "打开插件诊断",
                    "subtitle": "查看宿主资源、插件模块和错误日志",
                    "category": "诊断",
                    "route": "command-execute",
                    "payload": {},
                }
            ]
        }

    def _command_execute(self, payload, request_context):
        del payload, request_context
        self.context.open_detail_view()
        return {"executed": True}


__all__ = ["PluginDiagnosticsPlugin"]
