import os
import subprocess
from pathlib import Path

from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from plugins.gateway_manager.gateway import GatewayRuntime
from plugins.gateway_manager.models import GatewayDatabase
from plugins.gateway_manager.views import GatewayManagerWidget, GatewaySidebarWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget
from qfluentwidgets import BodyLabel, FluentIcon


class GatewayManagerPlugin(PluginBase):
    def __init__(self, context):
        super().__init__(context)
        self.description = "Manage local async path gateways"
        self.ui_widget = None
        self.sidebar_widget = None

        self.data_dir = Path(self.context.get_data_dir())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "gateway.db"

        self.db = GatewayDatabase(str(self.db_path))
        self.runtime = GatewayRuntime()
        self._active_gateway_ids = set()
        self.cloudflare_processes = {}
        self.cloudflare_last_errors = {}
        self.cloudflare_last_exit_codes = {}

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._on_status_timer)
        self.status_timer.start(1000)

    def on_load(self):
        logger.info("Gateway Manager loading...")
        auto_config = self.db.get_runtime_config(auto_only=True)
        if auto_config:
            self._active_gateway_ids = {item["id"] for item in auto_config}
            self.runtime.start(auto_config)

        for tunnel in self.db.get_cloudflare_tunnels_for_runtime(auto_only=True):
            self.start_cloudflare_tunnel(tunnel["id"])

    def on_unload(self):
        logger.info("Gateway Manager unloading...")
        self.status_timer.stop()
        self.stop_all_cloudflare_tunnels()
        self.runtime.stop()
        self.db.close()

    def get_card_widget(self) -> QWidget:
        if self.ui_widget is None:
            self.ui_widget = GatewayManagerWidget(self.db, self)
        return self.ui_widget

    def get_sidebar_widget(self) -> QWidget:
        if self.sidebar_widget is None:
            self.sidebar_widget = GatewaySidebarWidget()
            self._update_sidebar_status()
        return self.sidebar_widget

    def get_sidebar_widget_config(self) -> dict:
        return {"max_height": 40, "max_width": 60}

    def get_icon(self):
        return FluentIcon.IOT

    def get_thumbnail_widget(self) -> QWidget:
        label = BodyLabel("GW")
        label.setFixedSize(40, 40)
        label.setAlignment(Qt.AlignCenter)
        return label

    def start_all(self):
        config = self.db.get_runtime_config(auto_only=False)
        self._active_gateway_ids = {item["id"] for item in config}
        return self.runtime.start(config)

    def stop_all(self):
        self._active_gateway_ids.clear()
        self.runtime.stop()
        self._update_sidebar_status()
        if self.ui_widget:
            self.ui_widget.refresh_status()
        return True

    def start_gateway(self, gateway_id):
        config = self._active_runtime_config(extra_gateway_id=gateway_id)
        if not any(item["id"] == gateway_id for item in config):
            return False
        self._active_gateway_ids.add(gateway_id)
        result = self.runtime.start(config)
        self._update_sidebar_status()
        if self.ui_widget:
            self.ui_widget.refresh_status()
        return result

    def stop_gateway(self, gateway_id):
        self._active_gateway_ids.discard(gateway_id)
        result = self.runtime.stop_gateway(gateway_id)
        self._update_sidebar_status()
        if self.ui_widget:
            self.ui_widget.refresh_status()
        return result

    def reload_runtime(self):
        if not self._active_gateway_ids:
            self._update_sidebar_status()
            if self.ui_widget:
                self.ui_widget.refresh_status()
            return True

        result = self.runtime.start(self._active_runtime_config())
        self._update_sidebar_status()
        if self.ui_widget:
            self.ui_widget.refresh_status()
        return result

    def get_status(self):
        return self.runtime.get_status()

    def get_logs(self):
        return self.runtime.get_logs()

    def running_count(self):
        return self.runtime.running_count()

    def start_cloudflare_tunnel(self, tunnel_id=None):
        if tunnel_id is None:
            return self.start_all_cloudflare_tunnels()

        tunnel = self.db.get_cloudflare_tunnel(tunnel_id)
        if not tunnel or not tunnel["enabled"]:
            self.cloudflare_last_errors[tunnel_id] = "Cloudflare tunnel is disabled or missing"
            return False

        if self.is_cloudflare_running(tunnel_id):
            return True

        token = (tunnel["token"] or "").strip()
        if not token:
            self.cloudflare_last_errors[tunnel_id] = "Cloudflare token is required"
            return False

        cloudflared_path = (tunnel["cloudflared_path"] or "cloudflared").strip()
        try:
            creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            process = subprocess.Popen(
                [cloudflared_path, "tunnel", "run", "--token", token],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=creation_flags,
                cwd=str(self.data_dir),
            )
            self.cloudflare_processes[tunnel_id] = process
            self.cloudflare_last_errors[tunnel_id] = ""
            self.cloudflare_last_exit_codes[tunnel_id] = None
            logger.info(f"cloudflared tunnel process started: {tunnel['name']}")
            return True
        except Exception as exc:
            self.cloudflare_processes.pop(tunnel_id, None)
            self.cloudflare_last_errors[tunnel_id] = str(exc)
            logger.error(f"Failed to start cloudflared tunnel: {exc}", exc_info=True)
            return False

    def start_all_cloudflare_tunnels(self):
        tunnels = self.db.get_cloudflare_tunnels_for_runtime(auto_only=False)
        ok = True
        for tunnel in tunnels:
            ok = self.start_cloudflare_tunnel(tunnel["id"]) and ok
        return ok

    def stop_cloudflare_tunnel(self, tunnel_id=None):
        if tunnel_id is None:
            return self.stop_all_cloudflare_tunnels()

        process = self.cloudflare_processes.get(tunnel_id)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)

        if process:
            self.cloudflare_last_exit_codes[tunnel_id] = process.poll()
        self.cloudflare_processes.pop(tunnel_id, None)
        logger.info(f"cloudflared tunnel process stopped: {tunnel_id}")
        return True

    def stop_all_cloudflare_tunnels(self):
        ok = True
        for tunnel_id in list(self.cloudflare_processes.keys()):
            ok = self.stop_cloudflare_tunnel(tunnel_id) and ok
        return ok

    def is_cloudflare_running(self, tunnel_id=None):
        if tunnel_id is None:
            return any(process.poll() is None for process in self.cloudflare_processes.values())
        process = self.cloudflare_processes.get(tunnel_id)
        return process is not None and process.poll() is None

    def get_cloudflare_statuses(self):
        statuses = {}
        for tunnel in self.db.list_cloudflare_tunnels():
            tunnel_id = tunnel["id"]
            process = self.cloudflare_processes.get(tunnel_id)
            running = process is not None and process.poll() is None
            statuses[tunnel_id] = {
                "id": tunnel_id,
                "running": running,
                "pid": process.pid if running else None,
                "last_error": self.cloudflare_last_errors.get(tunnel_id, ""),
                "last_exit_code": self.cloudflare_last_exit_codes.get(tunnel_id),
            }
        return statuses

    def get_cloudflare_status(self):
        statuses = self.get_cloudflare_statuses()
        running_count = sum(1 for item in statuses.values() if item["running"])
        return {
            "running": running_count > 0,
            "running_count": running_count,
            "total_count": len(statuses),
        }

    def _active_runtime_config(self, extra_gateway_id=None):
        active_ids = set(self._active_gateway_ids)
        if extra_gateway_id is not None:
            active_ids.add(extra_gateway_id)

        config = self.db.get_runtime_config(auto_only=False)
        valid_ids = {item["id"] for item in config}
        self._active_gateway_ids.intersection_update(valid_ids)
        return [item for item in config if item["id"] in active_ids]

    def _on_status_timer(self):
        self._check_cloudflare_process()
        self._update_sidebar_status()
        if self.ui_widget:
            self.ui_widget.refresh_status()

    def _update_sidebar_status(self):
        count = self.runtime.running_count()
        if self.sidebar_widget:
            self.sidebar_widget.set_count(count)
            show_setting = self.context.state.get("show_gateway_sidebar_status", True)
            self.sidebar_widget.setVisible(show_setting and count > 0)

    def _check_cloudflare_process(self):
        for tunnel_id, process in list(self.cloudflare_processes.items()):
            if process and process.poll() is not None:
                self.cloudflare_last_exit_codes[tunnel_id] = process.returncode
                if process.returncode != 0:
                    self.cloudflare_last_errors[tunnel_id] = f"cloudflared exited with code {process.returncode}"
                self.cloudflare_processes.pop(tunnel_id, None)
