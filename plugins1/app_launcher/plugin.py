import os
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
from .views import AppLauncherWidget


class AppLauncher(PluginBase):
    """
    Plugin to launch external applications with configurable paths and arguments.
    Supports multiple applications.
    """

    def __init__(self, context):
        super().__init__(context)
        # Default settings structure: {"apps": []}
        # App structure: {"id": str, "name": str, "exe_path": str, "arguments": str, "icon": str}
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

    def on_unload(self):
        self._save_settings()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
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
            logger.info(f"App Launcher launching: {command}")
            # Use Popen to launch without blocking
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
