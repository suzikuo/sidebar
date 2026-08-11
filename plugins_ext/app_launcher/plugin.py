from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.data_layer.path_utils import PathManager
from core.data_layer.json_store import load_json, save_json_atomic
from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from .command_line import parse_command_line


class AppLauncher(PluginBase):
    """
    Plugin to launch external applications with configurable paths and arguments.
    Supports multiple applications.
    """

    def __init__(self, context):
        super().__init__(context)
        # Default settings structure: {"apps": []}
        # App structure: {"id": str, "name": str, "exe_path": str, "arguments": str, "icon": str}
        # Chrome entries may also include app_type/use_ahk/window_* fields.
        self.settings = {"apps": []}
        self.ui_widget = None

        # Setup Data Paths
        self.data_dir = Path(self.context.get_data_dir())
        self.settings_file = self.data_dir / "settings.json"

        # Migrate Legacy Data
        PathManager.migrate_plugin_data(
            self.context.plugin_id, Path(__file__).parent, files=["settings.json"]
        )

    def on_load(self):
        logger.info("App Launcher loading...")
        self._load_settings()
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
            "backup-snapshot", self._backup_snapshot, exported_capability="backup.read"
        )
        self.context.register_api_route(
            "backup-restore", self._backup_restore, exported_capability="backup.write"
        )

    def on_unload(self):
        self._save_settings()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            from .views import AppLauncherWidget

            self.ui_widget = AppLauncherWidget()
            self.ui_widget.set_apps(self.settings.get("apps", []))

            # Connect signals
            self.ui_widget.app_added.connect(self.add_app)
            self.ui_widget.app_removed.connect(self.remove_app)
            self.ui_widget.app_updated.connect(self.update_app)
            self.ui_widget.launch_requested.connect(self.launch_app)

        return self.ui_widget

    def get_icon(self):
        """Sidebar icon"""
        return FluentIcon.TILES

    def get_thumbnail_widget(self) -> QWidget:
        """Not used in current sidebar implementation but required by base class"""
        from qfluentwidgets import TransparentToolButton

        btn = TransparentToolButton(FluentIcon.TILES)
        btn.setFixedSize(40, 40)
        btn.setToolTip("App Launcher")
        return btn

    def _load_settings(self):
        if self.settings_file.exists():
            try:
                data = load_json(self.settings_file, {})

                # Migration logic: Check if it's the old single-app format
                if "exe_path" in data and "apps" not in data:
                    logger.info("App Launcher migrating legacy settings...")
                    old_app = {
                        "id": str(uuid.uuid4()),
                        "name": data.get("custom_command") or "Application",
                        "exe_path": data.get("exe_path", ""),
                        "arguments": data.get("arguments", ""),
                        "icon": "application",
                    }
                    if old_app["exe_path"]:  # Only migrate if there was a path
                        self.settings["apps"] = [old_app]
                else:
                    self.settings.update(data)

            except (OSError, TypeError, ValueError) as e:
                logger.error(f"App Launcher load error: {e}", exc_info=True)

    def _save_settings(self):
        try:
            save_json_atomic(self.settings_file, self.settings)
        except (OSError, TypeError, ValueError) as e:
            logger.error(f"App Launcher save error: {e}", exc_info=True)

    def add_app(self, app_data: dict):
        if "id" not in app_data:
            app_data["id"] = str(uuid.uuid4())

        self.settings["apps"].append(app_data)
        self._save_settings()
        if self.ui_widget:
            self.ui_widget.set_apps(self.settings["apps"])

    def remove_app(self, app_id: str):
        self.settings["apps"] = [
            app for app in self.settings["apps"] if app["id"] != app_id
        ]
        self._save_settings()
        if self.ui_widget:
            self.ui_widget.set_apps(self.settings["apps"])

    def update_app(self, app_id: str, new_data: dict):
        for app in self.settings["apps"]:
            if app["id"] == app_id:
                app.update(new_data)
                break
        self._save_settings()
        if self.ui_widget:
            self.ui_widget.set_apps(self.settings["apps"])

    def launch_app(self, app_id: str):
        app = next((a for a in self.settings["apps"] if a["id"] == app_id), None)
        if not app:
            logger.warning(f"App Launcher: App not found: {app_id}")
            return

        exe_path = app.get("exe_path")
        if not exe_path or not os.path.exists(exe_path):
            from qfluentwidgets import MessageBox

            w = MessageBox(
                "Error",
                f"Executable not found:\n{exe_path}",
                self.ui_widget.window() if self.ui_widget else None,
            )
            w.exec()
            return

        try:
            args = parse_command_line(app.get("arguments", ""))
        except ValueError as e:
            from qfluentwidgets import MessageBox

            w = MessageBox(
                "Invalid Arguments",
                str(e),
                self.ui_widget.window() if self.ui_widget else None,
            )
            w.exec()
            return
        command = [exe_path] + args

        try:
            if app.get("app_type") == "chrome" and app.get("use_ahk"):
                self._launch_with_ahk(app, command)
            else:
                logger.info(f"App Launcher launching: {command}")
                cwd = os.path.dirname(exe_path)
                subprocess.Popen(command, shell=False, cwd=cwd)
            self.context.close_detail_view()
        except Exception as e:
            from qfluentwidgets import MessageBox

            w = MessageBox(
                "Launch Failed",
                str(e),
                self.ui_widget.window() if self.ui_widget else None,
            )
            w.exec()

    def _command_catalog(self, payload, request_context):
        del payload, request_context
        return {
            "commands": [
                {
                    "id": app.get("id", ""),
                    "name": app.get("name") or "应用",
                    "subtitle": app.get("exe_path") or "",
                    "category": "应用",
                    "route": "command-execute",
                    "payload": {"id": app.get("id", "")},
                }
                for app in self.settings.get("apps", [])
                if app.get("id")
            ]
        }

    def _command_execute(self, payload, request_context):
        del request_context
        app_id = str(payload.get("id") or "")
        if not any(app.get("id") == app_id for app in self.settings.get("apps", [])):
            raise ValueError("应用不存在。")
        self.launch_app(app_id)
        return {"executed": True}

    def _backup_snapshot(self, payload, request_context):
        del payload, request_context
        return {"version": 1, "settings": self.settings}

    def _backup_restore(self, payload, request_context):
        del request_context
        settings = payload.get("settings")
        apps = settings.get("apps") if isinstance(settings, dict) else None
        if not isinstance(apps, list) or not all(isinstance(item, dict) for item in apps):
            raise ValueError("应用启动器备份格式无效。")
        self.settings = {"apps": [dict(item) for item in apps]}
        self._save_settings()
        if self.ui_widget is not None:
            self.ui_widget.set_apps(self.settings["apps"])
        return {"restored": len(apps)}

    def _launch_with_ahk(self, app: dict, command: list[str]):
        ahk_path = self._resolve_ahk_path(app.get("ahk_path", ""))
        if not ahk_path:
            raise FileNotFoundError(
                "AutoHotkey was not found. Install AutoHotkey or set its path in this Chrome entry."
            )

        script_dir = self.data_dir / "ahk"
        script_dir.mkdir(parents=True, exist_ok=True)
        script_path = script_dir / f"{app.get('id') or 'chrome'}.ahk"
        script_path.write_text(
            self._build_ahk_script(ahk_path, app, command),
            encoding="utf-8",
        )

        logger.info(f"App Launcher launching Chrome via AutoHotkey: {script_path}")
        subprocess.Popen([ahk_path, str(script_path)], shell=False)

    def _resolve_ahk_path(self, configured_path: str) -> str:
        expanded = os.path.expandvars(str(configured_path or "")).strip().strip('"')
        candidates = []
        if expanded:
            candidates.append(expanded)

        for env_key in ("ProgramFiles", "ProgramFiles(x86)"):
            root = os.environ.get(env_key)
            if root:
                candidates.extend(
                    [
                        os.path.join(root, "AutoHotkey", "AutoHotkey.exe"),
                        os.path.join(root, "AutoHotkey", "v2", "AutoHotkey64.exe"),
                        os.path.join(root, "AutoHotkey", "v2", "AutoHotkey.exe"),
                    ]
                )

        for name in ("AutoHotkey.exe", "AutoHotkey64.exe", "AutoHotkey32.exe"):
            found = shutil.which(name)
            if found:
                candidates.append(found)

        return next((path for path in candidates if path and os.path.exists(path)), "")

    def _build_ahk_script(self, ahk_path: str, app: dict, command: list[str]) -> str:
        command_line = subprocess.list2cmdline(command)
        exe_name = os.path.basename(command[0]) or "chrome.exe"
        target = f"ahk_exe {exe_name}"
        x = int(app.get("window_x", 200))
        y = int(app.get("window_y", 200))
        width = max(1, int(app.get("window_width", 160)))
        height = max(1, int(app.get("window_height", 400)))
        always_on_top = bool(app.get("always_on_top", True))

        if self._looks_like_ahk_v2(ahk_path):
            lines = [
                "#SingleInstance Force",
                f"Run {self._ahk_v2_quote(command_line)}",
                f"WinWaitActive {self._ahk_v2_quote(target)},, 10",
                f"WinMove {x}, {y}, {width}, {height}, {self._ahk_v2_quote(target)}",
            ]
            if always_on_top:
                lines.append(f"WinSetAlwaysOnTop 1, {self._ahk_v2_quote(target)}")
            return "\n".join(lines) + "\n"

        lines = [
            "#SingleInstance Force",
            f"Run, % {self._ahk_v1_quote(command_line)}",
            f"WinWaitActive, {target},, 10",
            f"WinMove, {target},,{x},{y},{width},{height}",
        ]
        if always_on_top:
            lines.append(f"WinSet, AlwaysOnTop, On, {target}")
        return "\n".join(lines) + "\n"

    def _looks_like_ahk_v2(self, ahk_path: str) -> bool:
        normalized = str(ahk_path or "").replace("/", "\\").lower()
        return "\\v2\\" in normalized

    def _ahk_v1_quote(self, value: str) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    def _ahk_v2_quote(self, value: str) -> str:
        return '"' + str(value).replace("`", "``").replace('"', '`"') + '"'
