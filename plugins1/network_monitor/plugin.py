"""Agile Tiles network monitor plugin entry point."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon, TransparentToolButton

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase

from .floating import FloatingNetworkWidget
from .service import NetworkMonitorService, normalize_config, validate_config
from .views import NetworkMonitorWidget


class NetworkMonitorPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.name = "网络监控"
        self.description = "查看系统、v2rayN 代理和直连的实时网速"
        self._service = None
        self._detail_widget = None
        self._floating_widget = None
        self._latest_snapshot = None
        self._config = None

    def on_load(self):
        self._config = normalize_config(self.context.state.get("config", {}))
        self.context.state.set("config", self._config)
        self._floating_widget = FloatingNetworkWidget()
        self._floating_widget.position_changed.connect(self._on_floating_moved)
        self._floating_widget.apply_config(self._config)
        self._service = NetworkMonitorService(self.context, self._config)
        self._service.snapshot_ready.connect(self._on_snapshot)
        self._service.start()
        logger.info("Network monitor plugin loaded.")

    def on_unload(self):
        if self._service is not None:
            self._service.stop()
        if self._floating_widget is not None:
            self._floating_widget.close()
            self._floating_widget.deleteLater()
        self._service = None
        self._detail_widget = None
        self._floating_widget = None
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
            if self._latest_snapshot is not None:
                self._detail_widget.set_snapshot(self._latest_snapshot)
        return self._detail_widget

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


__all__ = ["NetworkMonitorPlugin"]
