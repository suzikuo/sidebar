import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.data_layer.path_utils import PathManager
from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from plugins.frp_manager.models import DatabaseManager
from plugins.frp_manager.views import FRPManagerWidget, FRPSidebarWidget


class FRPManagerPlugin(PluginBase):
    """
    Plugin to manage FRP services.
    """

    def __init__(self, context):
        super().__init__(context)
        self.ui_widget = None
        self.sidebar_widget = None

        # Setup Data Paths
        self.data_dir = Path(self.context.get_data_dir())
        self.db_path = self.data_dir / "frp.db"

        # Migrate Legacy Data
        PathManager.migrate_plugin_data(
            self.context.plugin_id, Path(__file__).parent, files=["frp.db"]
        )

        self.db = DatabaseManager(str(self.db_path))
        self.processes = {}  # config_id -> subprocess.Popen

        # Timer for status updates if needed
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._check_processes)
        self.status_timer.start(2000)

    def on_load(self):
        logger.info("FRP Manager loading...")

    def on_unload(self):
        logger.info("FRP Manager unloading... Stopping all processes.")
        self.status_timer.stop()
        for config_id in list(self.processes.keys()):
            self.stop_frp(config_id)
        self.db.close()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = FRPManagerWidget(self.db, self)
        return self.ui_widget

    def get_sidebar_widget(self) -> QWidget:
        if self.sidebar_widget is None:
            self.sidebar_widget = FRPSidebarWidget()
            self._update_sidebar_status()
        return self.sidebar_widget

    def get_sidebar_widget_config(self) -> dict:
        return {"max_height": 40, "max_width": 60}

    def _update_sidebar_status(self):
        if self.sidebar_widget:
            running_count = sum(1 for p in self.processes.values() if p.poll() is None)
            self.sidebar_widget.set_count(running_count)

            # Visibility logic:
            # 1. User must have enabled it in settings
            # 2. Count must be > 0 (as per latest request)
            show_setting = self.context.state.get("show_sidebar_status", True)
            is_visible = show_setting and (running_count > 0)
            self.sidebar_widget.setVisible(is_visible)

    def get_icon(self):
        return FluentIcon.IOT

    def get_thumbnail_widget(self) -> QWidget:
        from qfluentwidgets import BodyLabel

        label = BodyLabel("FRP")
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignCenter)

        return label

    def start_frp(self, config_id):
        """Start an FRP service."""
        if config_id in self.processes:
            if self.processes[config_id].poll() is None:
                logger.info(f"FRP Service {config_id} is already running.")
                return True
            else:
                del self.processes[config_id]

        config = self.db.fetchone(
            "SELECT * FROM frp_configs WHERE id = ?", (config_id,)
        )
        if not config:
            return False

        exe_path = config["exe_path"]
        config_path = config["config_path"]

        if not os.path.exists(exe_path):
            logger.error(f"FRP Executable not found: {exe_path}")
            return False
        if not os.path.exists(config_path):
            logger.error(f"FRP Config not found: {config_path}")
            return False

        try:
            # Command: exe -c config
            cmd = [exe_path, "-c", config_path]
            logger.info(f"Starting FRP: {' '.join(cmd)}")

            # Start process in background, without window
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
                cwd=os.path.dirname(exe_path),
            )
            self.processes[config_id] = process
            self._update_sidebar_status()

            # Notify success
            if self.context:
                self.context.send_notification(
                    title="FRP Manager",
                    message=f"Service started: {config['name']}",
                )

            return True
        except Exception as e:
            msg = f"Error starting FRP: {e}"
            logger.error(msg, exc_info=True)

            if self.context:
                self.context.send_notification(
                    title="FRP Manager Error",
                    message=msg,
                )
            return False

    def stop_frp(self, config_id):
        """Stop an FRP service."""
        if config_id in self.processes:
            process = self.processes[config_id]
            if process.poll() is None:
                logger.info(f"Stopping FRP service {config_id}")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

            del self.processes[config_id]
            self._update_sidebar_status()

            # Notify stop
            if self.context:
                self.context.send_notification(
                    title="FRP Manager",
                    message="Service stopped",
                )

            return True
        return False

    def is_running(self, config_id):
        """Check if an FRP service is running."""
        if config_id in self.processes:
            if self.processes[config_id].poll() is None:
                return True
            else:
                del self.processes[config_id]
        return False

    def _check_processes(self):
        """Periodically check processes and notify UI if any stopped unexpectedly."""
        status_changed = False
        for config_id in list(self.processes.keys()):
            process = self.processes[config_id]
            if process.poll() is not None:
                msg = f"FRP Service {config_id} stopped with code {process.returncode}"
                logger.warning(msg)

                # Notify unexpected stop
                if self.context:
                    self.context.send_notification(
                        title="FRP Manager Warning",
                        message=msg,
                    )

                # Read output if any (process is already finished)
                try:
                    # We use communicate with a small timeout or just read from the pipe since it's already done
                    stdout_data = process.stdout.read()
                    if stdout_data:
                        logger.info(f"FRP Service {config_id} logs:\n{stdout_data}")
                except Exception as e:
                    logger.error(
                        f"Could not read logs for FRP service {config_id}: {e}",
                        exc_info=True,
                    )

                del self.processes[config_id]
                status_changed = True

        if status_changed:
            self._update_sidebar_status()
            if self.ui_widget:
                self.ui_widget.refresh_list()
