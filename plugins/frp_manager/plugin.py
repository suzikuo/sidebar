import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import FluentIcon

from core.data_layer.path_utils import PathManager
from core.plugin_system.plugin_base import PluginBase
from plugins.frp_manager.models import DatabaseManager
from plugins.frp_manager.views import FRPManagerWidget


class FRPManagerPlugin(PluginBase):
    """
    Plugin to manage FRP services.
    """

    def __init__(self, context):
        super().__init__(context)
        self.ui_widget = None

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
        print("[FRPManagerPlugin] Loading...")

    def on_unload(self):
        print("[FRPManagerPlugin] Unloading... Stopping all processes.")
        self.status_timer.stop()
        for config_id in list(self.processes.keys()):
            self.stop_frp(config_id)
        self.db.close()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = FRPManagerWidget(self.db, self)
        return self.ui_widget

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
                print(f"[FRPManagerPlugin] Service {config_id} is already running.")
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
            print(f"[FRPManagerPlugin] Executable not found: {exe_path}")
            return False
        if not os.path.exists(config_path):
            print(f"[FRPManagerPlugin] Config not found: {config_path}")
            return False

        try:
            # Command: exe -c config
            cmd = [exe_path, "-c", config_path]
            print(f"[FRPManagerPlugin] Starting: {' '.join(cmd)}")

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

            # Notify success
            if self.context:
                self.context.send_notification(
                    title="FRP Manager",
                    message=f"Service started: {config['name']}",
                )

            return True
        except Exception as e:
            msg = f"Error starting FRP: {e}"
            print(f"[FRPManagerPlugin] {msg}")

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
                print(f"[FRPManagerPlugin] Stopping service {config_id}")
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

            del self.processes[config_id]

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
                msg = f"Service {config_id} stopped with code {process.returncode}"
                print(f"[FRPManagerPlugin] {msg}")

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
                        print(
                            f"[FRPManagerPlugin] Service {config_id} logs:\n{stdout_data}"
                        )
                except Exception as e:
                    print(
                        f"[FRPManagerPlugin] Could not read logs for {config_id}: {e}"
                    )

                del self.processes[config_id]
                status_changed = True

        if status_changed and self.ui_widget:
            self.ui_widget.refresh_list()
