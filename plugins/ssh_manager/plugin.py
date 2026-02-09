import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, FluentIcon

from core.data_layer.path_utils import PathManager
from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from plugins.ssh_manager.models import DatabaseManager
from plugins.ssh_manager.views import SSHManagerWidget


class SSHManagerPlugin(PluginBase):
    """
    Plugin to manage and launch SSH connections.
    """

    def __init__(self, context):
        super().__init__(context)
        self.ui_widget = None

        # 1. Setup Data Paths
        plugin_data_dir = Path(self.context.get_data_dir())
        self.db_path = plugin_data_dir / "ssh.db"
        self.keys_dir = plugin_data_dir / "keys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        # 2. Migrate Legacy Data
        PathManager.migrate_plugin_data(
            self.context.plugin_id,
            Path(__file__).parent,
            files=["ssh.db"],
            dirs=["keys"],
        )

        # 3. Initialize DB
        self.db = DatabaseManager(str(self.db_path))

    def on_load(self):
        logger.info("SSH Manager loading...")
        # Migration: Add color column if missing
        try:
            self.db.execute("ALTER TABLE ssh_connections ADD COLUMN color TEXT")
            logger.info("SSH Manager migration: Added color column")
        except Exception:
            # Column likely already exists
            pass

    def on_unload(self):
        logger.info("SSH Manager unloading...")
        self.db.close()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = SSHManagerWidget(self.db, self.keys_dir)
            self.ui_widget.connect_requested.connect(self.connect_ssh)
            self.ui_widget.scp_requested.connect(self.run_scp)
        return self.ui_widget

    def get_icon(self):
        return FluentIcon.COMMAND_PROMPT

    def get_thumbnail_widget(self) -> QWidget:
        label = BodyLabel("SSH")
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignCenter)

        return label

    def connect_ssh(self, connection_id):
        """Launch SSH connection in a new terminal."""
        conn = self.db.fetchone(
            "SELECT * FROM ssh_connections WHERE id = ?", (connection_id,)
        )
        if not conn:
            return

        # conn is likely a dict or tuple depending on db implementation
        # Assuming fetchone returns a dict if using Row factory, or just index it
        # Let's check typical db usage in this app

        name = conn.get("name") if isinstance(conn, dict) else conn[1]
        host = conn.get("host") if isinstance(conn, dict) else conn[2]
        user = conn.get("user") if isinstance(conn, dict) else conn[3]
        port = conn.get("port") if isinstance(conn, dict) else conn[4]
        pem_path = conn.get("pem_path") if isinstance(conn, dict) else conn[5]

        # Reconstruct full path if pem_path is just a filename
        if pem_path and not os.path.isabs(pem_path):
            full_pem_path = self.keys_dir / pem_path
            if full_pem_path.exists():
                pem_path = str(full_pem_path)

        # Construct SSH command
        ssh_cmd = f"ssh {user}@{host} -p {port}"
        if pem_path and os.path.exists(pem_path):
            ssh_cmd += f' -i "{pem_path}"'

        # Use start to launch in a new cmd window
        # cmd /k stays open, cmd /c closes after command (ssh itself will keep it open until exit)
        # However, for SSH we usually want a separate shell.

        # On Windows, we can use 'start ssh ...'
        full_command = f'start "{name}" {ssh_cmd}'

        try:
            logger.info(f"Connecting to {name}: {ssh_cmd}")
            subprocess.Popen(full_command, shell=True)
        except Exception as e:
            logger.error(f"Error launching SSH: {e}", exc_info=True)

    def run_scp(self, connection_id, transfer_data):
        """Execute SCP command in a new terminal."""
        conn = self.db.fetchone(
            "SELECT * FROM ssh_connections WHERE id = ?", (connection_id,)
        )
        if not conn:
            return

        name = conn.get("name") if isinstance(conn, dict) else conn[1]
        host = conn.get("host") if isinstance(conn, dict) else conn[2]
        user = conn.get("user") if isinstance(conn, dict) else conn[3]
        port = conn.get("port") if isinstance(conn, dict) else conn[4]
        pem_path = conn.get("pem_path") if isinstance(conn, dict) else conn[5]

        # Reconstruct path
        if pem_path and not os.path.isabs(pem_path):
            pem_path = str(self.keys_dir / pem_path)

        mode = transfer_data["mode"]
        local_path = transfer_data["local_path"]
        remote_path = transfer_data["remote_path"]
        recursive = transfer_data["recursive"]

        # Construct SCP command
        # Windows scp: scp [-P port] [-i identity_file] [-r] source destination
        recursive_flag = "-r" if recursive else ""
        identity_flag = (
            f' -i "{pem_path}"' if pem_path and os.path.exists(pem_path) else ""
        )
        port_flag = f" -P {port}"

        if mode == "upload":
            source = f'"{local_path}"'
            destination = f"{user}@{host}:{remote_path}"
        else:
            source = f"{user}@{host}:{remote_path}"
            destination = f'"{local_path}"'

        scp_cmd = (
            f"scp{port_flag}{identity_flag} {recursive_flag} {source} {destination}"
        )
        full_command = f'start "SCP - {name}" cmd /k "{scp_cmd} && pause"'

        try:
            logger.info(f"Executing SCP: {scp_cmd}")
            subprocess.Popen(full_command, shell=True)
        except Exception as e:
            logger.error(f"Error launching SCP: {e}", exc_info=True)
