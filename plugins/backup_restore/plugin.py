from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase

from .models import normalize_profile
from .service import collect_plugin_snapshots, restore_plugin_snapshots


class BackupRestorePlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.description = "插件快照与显式文件备份"
        self._widget = None
        self._controller = None
        self._profiles = []

    def on_load(self):
        stored = self.context.state.get("profiles", [])
        for value in stored if isinstance(stored, list) else ():
            try:
                self._profiles.append(normalize_profile(value))
            except ValueError:
                logger.warning("Ignoring invalid backup profile.")
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
        self._save()
        if self._controller is not None:
            self._controller.deleteLater()
            self._controller = None
        if self._widget is not None:
            self._widget.close()
            self._widget.deleteLater()
            self._widget = None

    def get_icon(self):
        return FluentIcon.SAVE

    def get_thumbnail_widget(self):
        return None

    def get_card_widget(self) -> QWidget:
        if self._widget is None:
            from .controller import BackupController
            from .views import BackupRestoreWidget

            self._widget = BackupRestoreWidget()
            self._controller = BackupController(self.context, parent=self._widget)
            self._widget.profile_added.connect(self._add_profile)
            self._widget.profile_removed.connect(self._remove_profile)
            self._widget.backup_requested.connect(self._run_backup)
            self._widget.restore_requested.connect(self._controller.restore)
            self._controller.backup_created.connect(self._backup_created)
            self._controller.restore_ready.connect(self._restore_ready)
            self._controller.error.connect(self._widget.show_error)
            self._refresh()
        return self._widget

    def _add_profile(self, value):
        self._profiles.append(normalize_profile(value))
        self._save()
        self._refresh()

    def _remove_profile(self, profile_id):
        self._profiles = [item for item in self._profiles if item["id"] != profile_id]
        self._save()
        self._refresh()

    def _run_backup(self, profile_id):
        profile = next((item for item in self._profiles if item["id"] == profile_id), None)
        if profile is None:
            return
        snapshots = collect_plugin_snapshots(self.context)
        self._controller.create(dict(profile), snapshots)

    def _backup_created(self, result):
        profile_id = result["manifest"]["profile"]["id"]
        profile = next((item for item in self._profiles if item["id"] == profile_id), None)
        if profile is not None:
            profile["last_backup"] = datetime.now().astimezone().isoformat(timespec="seconds")
            self._save()
            self._refresh()
        self._widget.show_created(result["path"])

    def _restore_ready(self, result):
        snapshots = result["manifest"].get("pluginSnapshots", {})
        plugin_result = restore_plugin_snapshots(self.context, snapshots)
        result = dict(result)
        result["plugins"] = plugin_result["restored"]
        if plugin_result["errors"]:
            self._widget.show_error("；".join(plugin_result["errors"].values()))
        self._widget.show_restored(result)

    def _save(self):
        self.context.state.set("profiles", self._profiles)

    def _refresh(self):
        if self._widget is not None:
            self._widget.set_profiles(self._profiles)

    def _command_catalog(self, payload, request_context):
        del payload, request_context
        return {
            "commands": [
                {
                    "id": "open",
                    "name": "打开备份与恢复",
                    "subtitle": "插件快照与显式文件备份",
                    "category": "维护",
                    "route": "command-execute",
                    "payload": {},
                }
            ]
        }

    def _command_execute(self, payload, request_context):
        del payload, request_context
        self.context.open_detail_view()
        return {"executed": True}


__all__ = ["BackupRestorePlugin"]
