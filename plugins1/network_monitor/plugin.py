"""Agile Tiles network monitor plugin entry point."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, TransparentToolButton

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase

from .floating import FloatingNetworkWidget
from .history_api import TrafficHistoryApi
from .service import NetworkMonitorService, normalize_config, validate_config
from .views import NetworkMonitorWidget


class NetworkMonitorPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.name = "网络监控"
        self.description = "查看应用实时流量、独立来源历史趋势和悬浮网速"
        self._service = None
        self._detail_widget = None
        self._floating_widget = None
        self._latest_snapshot = None
        self._config = None
        self._history_api = None

    def on_load(self):
        self._config = normalize_config(self.context.state.get("config", {}))
        self.context.state.set("config", self._config)
        self._history_api = TrafficHistoryApi(
            self.context,
            f"{self.context.get_data_dir()}/traffic_history.db",
        )
        self._history_api.register_routes()
        if self._config["floating_enabled"]:
            self._ensure_floating_widget()
        self._service = NetworkMonitorService(self.context, self._config)
        self._service.snapshot_ready.connect(self._on_snapshot)
        self._service.history_ready.connect(self._on_history)
        self._service.start()
        logger.info("Network monitor plugin loaded.")

    def on_unload(self):
        if self._service is not None:
            self._service.stop()
        if self._floating_widget is not None:
            self._floating_widget.close()
            self._floating_widget.deleteLater()
        if self._history_api is not None:
            self._history_api.close()
        self._service = None
        self._detail_widget = None
        self._floating_widget = None
        self._history_api = None
        logger.info("Network monitor plugin unloaded.")

    def get_icon(self):
        return FluentIcon.SPEED_HIGH

    def get_thumbnail_widget(self) -> QWidget:
        button = TransparentToolButton(FluentIcon.SPEED_HIGH)
        button.setFixedSize(40, 40)
        button.setToolTip("网络监控")
        return button

    def get_card_widget(self) -> QWidget:
        if self._detail_widget is None:
            self._detail_widget = NetworkMonitorWidget()
            self._detail_widget.set_config(self._config or {})
            self._detail_widget.config_changed.connect(self._on_config_changed)
            self._detail_widget.history_requested.connect(
                self._service.request_history
            )
            if self._latest_snapshot is not None:
                self._detail_widget.set_snapshot(self._latest_snapshot)
        return self._detail_widget

    def _on_history(self, result):
        if self._detail_widget is not None:
            self._detail_widget.set_history_result(result)

    def _on_snapshot(self, snapshot):
        self._latest_snapshot = snapshot
        if self._detail_widget is not None:
            self._detail_widget.set_snapshot(snapshot)
        if self._floating_widget is not None:
            self._floating_widget.set_snapshot(snapshot)

    def _on_config_changed(self, value):
        try:
            config = validate_config({**(self._config or {}), **value})
            self._config = config
            self.context.state.set("config", config)
            if self._service is not None:
                self._service.apply_config(config)
            if config["floating_enabled"]:
                self._ensure_floating_widget()
            elif self._floating_widget is not None:
                self._floating_widget.close()
                self._floating_widget.deleteLater()
                self._floating_widget = None
            if self._floating_widget is not None:
                self._floating_widget.apply_config(config)
        except (TypeError, ValueError) as error:
            if self._detail_widget is not None:
                self._detail_widget.show_config_error(error)
            return
        if self._detail_widget is not None:
            self._detail_widget.set_config(config)
            self._detail_widget.show_config_saved()

    def _on_floating_moved(self, x, y):
        config = dict(self._config or normalize_config({}))
        config["floating_x"] = int(x)
        config["floating_y"] = int(y)
        self._config = normalize_config(config)
        self.context.state.set("config", self._config)

    def _ensure_floating_widget(self):
        if self._floating_widget is None:
            self._floating_widget = FloatingNetworkWidget()
            self._floating_widget.position_changed.connect(self._on_floating_moved)
        self._floating_widget.apply_config(self._config)
        if self._latest_snapshot is not None:
            self._floating_widget.set_snapshot(self._latest_snapshot)


__all__ = ["NetworkMonitorPlugin"]
