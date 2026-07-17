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

    SSH_KEEPALIVE_OPTIONS = (
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=6",
        "-o",
        "TCPKeepAlive=yes",
    )

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

    def on_unload(self):
        logger.info("SSH Manager unloading...")
        self.db.close()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = SSHManagerWidget(self.db, self.keys_dir)
            self.ui_widget.connect_requested.connect(self.connect_ssh)
        return self.ui_widget

    def get_icon(self):
        return FluentIcon.COMMAND_PROMPT

    def get_thumbnail_widget(self) -> QWidget:
        label = BodyLabel("SSH")
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignCenter)

        return label

    @staticmethod
    def _quote_cmd_arg(value):
        """Quote one argument for safe use inside a cmd.exe command string."""
        result = ['"']
        backslashes = 0
        for char in str(value):
            if char == "\\":
                backslashes += 1
                continue
            if char == '"':
                result.append("\\" * (backslashes * 2 + 1))
                result.append(char)
            else:
                result.append("\\" * backslashes)
                result.append(char)
            backslashes = 0
        result.append("\\" * (backslashes * 2))
        result.append('"')
        return "".join(result)

    @classmethod
    def _format_cmd(cls, args):
        """Build a cmd.exe command from argv-style parts."""
        if not args:
            return ""

        return " ".join(cls._format_cmd_arg(arg) for arg in args)

    @classmethod
    def _format_cmd_arg(cls, value):
        """Quote only arguments that cmd.exe actually needs quoted."""
        value = str(value)
        if value == "":
            return '""'

        needs_quotes = any(char.isspace() for char in value)
        needs_quotes = needs_quotes or any(char in '&|<>^"%!' for char in value)
        return cls._quote_cmd_arg(value) if needs_quotes else value

    @staticmethod
    def _safe_cmd_title(value, fallback="SSH"):
        title = str(value or fallback).strip()
        for char in '&|<>^"%!':
            title = title.replace(char, "")
        return title or fallback

    def _launch_cmd_window(self, title, command, exit_message):
        """Launch a command in a new Windows cmd window and keep it open."""
        full_command = (
            f"title {self._safe_cmd_title(title)}"
            f" & {command}"
            f" & echo."
            f" & echo {exit_message}"
        )
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        subprocess.Popen(["cmd.exe", "/k", full_command], creationflags=creationflags)

    def connect_ssh(self, connection_id):
        """Launch SSH connection in a new terminal."""
        conn = self.db.get_connection(connection_id)
        if not conn:
            return

        # conn is likely a dict or tuple depending on db implementation
        # Assuming fetchone returns a dict if using Row factory, or just index it
        # Let's check typical db usage in this app

        name = conn["name"]
        host = conn["host"]
        user = conn["user"]
        port = conn["port"]
        pem_path = conn["pem_path"]

        # Reconstruct full path if pem_path is just a filename
        if pem_path and not os.path.isabs(pem_path):
            full_pem_path = self.keys_dir / pem_path
            if full_pem_path.exists():
                pem_path = str(full_pem_path)

        # Construct SSH command
        ssh_args = [
            "ssh",
            "-p",
            str(port),
            *self.SSH_KEEPALIVE_OPTIONS,
        ]
        if pem_path and os.path.exists(pem_path):
            ssh_args.extend(["-i", pem_path])
        ssh_args.append(f"{user}@{host}")
        ssh_cmd = self._format_cmd(ssh_args)

        try:
            logger.info(f"Connecting to {name}: {ssh_cmd}")
            self._launch_cmd_window(
                name,
                ssh_cmd,
                "SSH session ended. This window is kept open so you can read the reason or reconnect.",
            )
        except Exception as e:
            logger.error(f"Error launching SSH: {e}", exc_info=True)

    def run_scp(self, connection_id, transfer_data):
        """Execute SCP command in a new terminal."""
        conn = self.db.get_connection(connection_id)
        if not conn:
            return

        name = conn["name"]
        host = conn["host"]
        user = conn["user"]
        port = conn["port"]
        pem_path = conn["pem_path"]

        # Reconstruct path
        if pem_path and not os.path.isabs(pem_path):
            pem_path = str(self.keys_dir / pem_path)

        mode = transfer_data["mode"]
        local_path = transfer_data["local_path"]
        remote_path = transfer_data["remote_path"]
        recursive = transfer_data["recursive"]

        if mode == "upload":
            source = local_path
            destination = f"{user}@{host}:{remote_path}"
        else:
            source = f"{user}@{host}:{remote_path}"
            destination = local_path

        scp_args = ["scp", "-P", str(port)]
        if pem_path and os.path.exists(pem_path):
            scp_args.extend(["-i", pem_path])
        if recursive:
            scp_args.append("-r")
        scp_args.extend([source, destination])
        scp_cmd = self._format_cmd(scp_args)

        try:
            logger.info(f"Executing SCP: {scp_cmd}")
            self._launch_cmd_window(
                f"SCP - {name}",
                scp_cmd,
                "SCP command ended. This window is kept open so you can read the result.",
            )
        except Exception as e:
            logger.error(f"Error launching SCP: {e}", exc_info=True)
