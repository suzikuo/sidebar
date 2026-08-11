from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase


class SystemMonitorPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.description = "CPU、内存、磁盘和进程"
        self._widget = None
        self._service = None
        self._interval_ms = self._normalize_interval(
            self.context.state.get("interval_ms", 2000)
        )

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
        self.context.register_api_route(
            "backup-snapshot",
            self._backup_snapshot,
            exported_capability="backup.read",
        )
        self.context.register_api_route(
            "backup-restore",
            self._backup_restore,
            exported_capability="backup.write",
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
        return FluentIcon.SPEED_HIGH

    def get_thumbnail_widget(self):
        return None

    def get_card_widget(self) -> QWidget:
        if self._widget is None:
            from .service import SystemMonitorService
            from .views import SystemMonitorWidget

            self._widget = SystemMonitorWidget(self._interval_ms)
            self._service = SystemMonitorService(
                self.context,
                interval_ms=self._interval_ms,
                parent=self._widget,
            )
            self._widget.active_changed.connect(self._set_active)
            self._widget.refresh_requested.connect(self._service.request_refresh)
            self._widget.interval_changed.connect(self._set_interval)
            self._widget.terminate_requested.connect(self._terminate)
            self._service.snapshot_ready.connect(self._widget.apply_snapshot)
            self._service.error.connect(self._widget.show_error)
        return self._widget

    def _set_active(self, active):
        if active:
            self._service.start()
        else:
            self._service.stop()

    def _set_interval(self, interval_ms):
        self._interval_ms = self._normalize_interval(interval_ms)
        self.context.state.set("interval_ms", self._interval_ms)
        if self._service is not None:
            self._service.set_interval(self._interval_ms)

    def _terminate(self, pid):
        try:
            self._service.terminate(pid)
        except Exception as error:
            logger.error("Failed to terminate process %s: %s", pid, error, exc_info=True)
            self._widget.show_error(error)

    def _backup_snapshot(self, payload, request_context):
        del payload, request_context
        return {"version": 1, "intervalMs": self._interval_ms}

    def _command_catalog(self, payload, request_context):
        del payload, request_context
        return {
            "commands": [
                {
                    "id": "open",
                    "name": "打开系统监控",
                    "subtitle": "CPU、内存、磁盘和进程",
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

    def _backup_restore(self, payload, request_context):
        del request_context
        self._set_interval(payload.get("intervalMs", 2000))
        return {"restored": True}

    @staticmethod
    def _normalize_interval(value):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = 2000
        return parsed if parsed in {1000, 2000, 5000} else 2000


__all__ = ["SystemMonitorPlugin"]
