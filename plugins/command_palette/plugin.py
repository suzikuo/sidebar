from __future__ import annotations

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase

from .models import normalize_custom_command
from .service import collect_commands, execute_command


class CommandPalettePlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.description = "统一搜索和执行常用命令"
        self._widget = None
        self._custom_commands = []

    def on_load(self):
        stored = self.context.state.get("custom_commands", [])
        for value in stored if isinstance(stored, list) else ():
            try:
                self._custom_commands.append(normalize_custom_command(value))
            except ValueError:
                logger.warning("Ignoring invalid custom command in saved state.")
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
        self._save()
        if self._widget is not None:
            self._widget.close()
            self._widget.deleteLater()
            self._widget = None

    def get_icon(self):
        return FluentIcon.SEARCH

    def get_thumbnail_widget(self):
        return None

    def get_card_widget(self) -> QWidget:
        if self._widget is None:
            from .views import CommandPaletteWidget

            self._widget = CommandPaletteWidget()
            self._widget.execute_requested.connect(self._execute)
            self._widget.add_requested.connect(self._add)
            self._widget.remove_requested.connect(self._remove)
            self._widget.refresh_requested.connect(self._refresh)
            self._refresh()
        return self._widget

    def _refresh(self):
        if self._widget is not None:
            self._widget.set_commands(
                collect_commands(self.context, self._custom_commands)
            )

    def _execute(self, command):
        try:
            execute_command(self.context, command)
        except Exception as error:
            logger.error("Command execution failed: %s", error, exc_info=True)
            if self._widget is not None:
                self._widget.show_error(error)
            return
        self.context.close_detail_view()

    def _add(self, value):
        self._custom_commands.append(normalize_custom_command(value))
        self._save()
        self._refresh()

    def _remove(self, command_id):
        self._custom_commands = [
            command for command in self._custom_commands if command["id"] != command_id
        ]
        self._save()
        self._refresh()

    def _save(self):
        self.context.state.set("custom_commands", self._custom_commands)

    def _backup_snapshot(self, payload, request_context):
        del payload, request_context
        return {"version": 1, "customCommands": self._custom_commands}

    def _backup_restore(self, payload, request_context):
        del request_context
        values = payload.get("customCommands", [])
        restored = []
        for value in values if isinstance(values, list) else ():
            restored.append(normalize_custom_command(value))
        self._custom_commands = restored
        self._save()
        self._refresh()
        return {"restored": len(restored)}


__all__ = ["CommandPalettePlugin"]
