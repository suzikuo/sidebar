import os
import sqlite3
import subprocess
from pathlib import Path

from core.api_gateway import ApiError
from core.logger import logger
from core.plugin_system.plugin_base import PluginBase
from plugins.gateway_manager.gateway import GatewayRuntime
from plugins.gateway_manager.models import GatewayDatabase, validate_target_url
from plugins.gateway_manager.web_view import GatewayInterface
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
        self.web_widget = None

        self.data_dir = Path(self.context.get_data_dir())
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "gateway.db"

        self.db = GatewayDatabase(str(self.db_path))
        self.runtime = GatewayRuntime()
        self._active_gateway_ids = set()
        self.cloudflare_processes = {}
        self.cloudflare_last_errors = {}
        self.cloudflare_last_exit_codes = {}
        self._last_sidebar_status = None

        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self._on_status_timer)
        self.status_timer.start(1000)

    def on_load(self):
        logger.info("Gateway Manager loading...")
        self._register_web_api()
        auto_config = self.db.get_runtime_config(auto_only=True)
        if auto_config:
            self._active_gateway_ids = {item["id"] for item in auto_config}
            self.runtime.start(auto_config)

        for tunnel in self.db.get_cloudflare_tunnels_for_runtime(auto_only=True):
            self.start_cloudflare_tunnel(tunnel["id"])

    def on_unload(self):
        logger.info("Gateway Manager unloading...")
        self.status_timer.stop()
        self.status_timer.timeout.disconnect(self._on_status_timer)
        self.status_timer.deleteLater()
        if self.web_widget:
            self.web_widget.dispose()
            self.web_widget.deleteLater()
            self.web_widget = None
            self.ui_widget = None
        self.stop_all_cloudflare_tunnels()
        self.runtime.stop()
        self.db.close()

    def get_card_widget(self) -> QWidget:
        if self.web_widget is None:
            self.web_widget = GatewayInterface(
                self.context.api_registry,
                Path(__file__).with_name("web"),
                self._get_native_widget,
            )
        return self.web_widget

    def _get_native_widget(self):
        if self.ui_widget is None:
            self.ui_widget = GatewayManagerWidget(self.db, self)
        return self.ui_widget

    def get_sidebar_widget(self) -> QWidget:
        if self.sidebar_widget is None:
            self.sidebar_widget = GatewaySidebarWidget()
            self._update_sidebar_status()
        return self.sidebar_widget

    def get_sidebar_widget_config(self) -> dict:
        # Reserve exactly one navigation cell.  The widget is intentionally
        # icon-only so a narrow or short sidebar never needs to reflow text.
        return {
            "min_height": 40,
            "max_height": 40,
            "min_width": 40,
            "max_width": 40,
        }

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
        if self.ui_widget and self.ui_widget.isVisible():
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

    def _register_web_api(self):
        self.context.register_api_route("snapshot", self._web_snapshot)
        self.context.register_api_route("action", self._web_action)
        self.context.register_api_route("save", self._web_save)
        self.context.register_api_route("delete", self._web_delete)

    def _web_snapshot(self, payload, request_context):
        del payload, request_context
        gateway_status = self.get_status()
        gateways = []
        for row in self.db.list_gateways():
            gateway = dict(row)
            status = gateway_status.get(gateway["id"], {})
            gateways.append(
                {
                    "id": gateway["id"],
                    "name": gateway["name"],
                    "listen_host": gateway["listen_host"],
                    "listen_port": int(gateway["listen_port"]),
                    "enabled": bool(gateway["enabled"]),
                    "auto_start": bool(gateway["auto_start"]),
                    "remarks": gateway["remarks"] or "",
                    "running": bool(status.get("running")),
                    "error": status.get("error") or "",
                    "routes_count": int(status.get("routes") or 0),
                    "requests_total": int(status.get("requests_total") or 0),
                    "last_request_at": float(status.get("last_request_at") or 0),
                }
            )

        tunnels = []
        tunnel_statuses = self.get_cloudflare_statuses()
        for row in self.db.list_cloudflare_tunnels():
            tunnel = dict(row)
            status = tunnel_statuses.get(tunnel["id"], {})
            tunnels.append(
                {
                    "id": tunnel["id"],
                    "name": tunnel["name"],
                    "cloudflared_path": tunnel["cloudflared_path"] or "cloudflared",
                    "gateway_id": tunnel["gateway_id"],
                    "gateway_name": tunnel["gateway_name"] or "",
                    "enabled": bool(tunnel["enabled"]),
                    "auto_start": bool(tunnel["auto_start"]),
                    "remarks": tunnel["remarks"] or "",
                    "has_token": bool(tunnel["token"]),
                    "running": bool(status.get("running")),
                    "pid": status.get("pid"),
                    "last_error": status.get("last_error") or "",
                    "last_exit_code": status.get("last_exit_code"),
                }
            )

        services = [
            {
                "id": row["id"],
                "name": row["name"],
                "target_url": row["target_url"],
                "enabled": bool(row["enabled"]),
                "remarks": row["remarks"] or "",
            }
            for row in self.db.list_services()
        ]
        routes = [
            {
                "id": row["id"],
                "gateway_id": row["gateway_id"],
                "gateway_name": row["gateway_name"],
                "service_id": row["service_id"],
                "service_name": row["service_name"],
                "target_url": row["target_url"],
                "path_prefix": row["path_prefix"],
                "preserve_host": bool(row["preserve_host"]),
                "enabled": bool(row["enabled"]),
            }
            for row in self.db.list_routes()
        ]
        return {
            "running_count": self.running_count(),
            "total_gateways": len(gateways),
            "gateways": gateways,
            "tunnels": tunnels,
            "services": services,
            "routes": routes,
            "logs": self.get_logs(),
        }

    def _web_action(self, payload, request_context):
        del request_context
        action = str(payload.get("action") or "")
        item_id = self._optional_item_id(payload.get("id"))
        if action == "start_all":
            succeeded = self.start_all()
        elif action == "stop_all":
            succeeded = self.stop_all()
        elif action == "start_all_tunnels":
            succeeded = self.start_all_cloudflare_tunnels()
        elif action == "stop_all_tunnels":
            succeeded = self.stop_all_cloudflare_tunnels()
        elif action == "start_gateway":
            succeeded = self.start_gateway(self._required_item_id(item_id))
        elif action == "stop_gateway":
            succeeded = self.stop_gateway(self._required_item_id(item_id))
        elif action == "start_tunnel":
            succeeded = self.start_cloudflare_tunnel(self._required_item_id(item_id))
        elif action == "stop_tunnel":
            succeeded = self.stop_cloudflare_tunnel(self._required_item_id(item_id))
        else:
            raise ApiError("INVALID_REQUEST", "不支持的网关操作。")
        self._update_sidebar_status()
        if not succeeded:
            raise ApiError("ACTION_FAILED", "网关操作未成功，请查看状态信息。")
        return self._web_snapshot({}, None)

    def _web_save(self, payload, request_context):
        del request_context
        resource = str(payload.get("resource") or "")
        data = payload.get("data")
        item_id = self._optional_item_id(payload.get("id"))
        if not isinstance(data, dict):
            raise ApiError("INVALID_REQUEST", "保存内容必须是对象。")

        try:
            if resource == "service":
                if not validate_target_url(data.get("target_url")):
                    raise ValueError("服务目标地址必须是有效的 HTTP 或 HTTPS 地址。")
                self.db.save_service(data, item_id)
                self.reload_runtime()
            elif resource == "gateway":
                self.db.save_gateway(data, item_id)
                self.reload_runtime()
            elif resource == "route":
                self.db.save_route(data, item_id)
                self.reload_runtime()
            elif resource == "tunnel":
                was_running = bool(item_id and self.is_cloudflare_running(item_id))
                existing = self.db.get_cloudflare_tunnel(item_id) if item_id else None
                if item_id and not existing:
                    raise ApiError("NOT_FOUND", "Cloudflare Tunnel 不存在。")
                if not str(data.get("name") or "").strip():
                    raise ValueError("Tunnel 名称不能为空。")
                data = dict(data)
                data["gateway_id"] = self._optional_item_id(data.get("gateway_id"))
                data["token"] = str(data.get("token") or "").strip() or (existing or {}).get("token", "")
                if not data["token"]:
                    raise ValueError("新 Tunnel 必须填写 token。")
                self.db.save_cloudflare_tunnel(data, item_id)
                if was_running:
                    self.stop_cloudflare_tunnel(item_id)
                    self.start_cloudflare_tunnel(item_id)
            else:
                raise ApiError("INVALID_REQUEST", "不支持的配置类型。")
        except (TypeError, ValueError, sqlite3.Error) as exc:
            raise ApiError("INVALID_REQUEST", str(exc)) from exc
        return self._web_snapshot({}, None)

    def _web_delete(self, payload, request_context):
        del request_context
        resource = str(payload.get("resource") or "")
        item_id = self._required_item_id(self._optional_item_id(payload.get("id")))
        try:
            if resource == "service":
                deleted = self.db.delete_service(item_id)
                self.reload_runtime()
            elif resource == "gateway":
                self.stop_gateway(item_id)
                deleted = self.db.delete_gateway(item_id)
                self.reload_runtime()
            elif resource == "route":
                deleted = self.db.delete_route(item_id)
                self.reload_runtime()
            elif resource == "tunnel":
                self.stop_cloudflare_tunnel(item_id)
                deleted = self.db.delete_cloudflare_tunnel(item_id)
                deleted = True if deleted is None else deleted
            else:
                raise ApiError("INVALID_REQUEST", "不支持的配置类型。")
        except sqlite3.Error as exc:
            raise ApiError("INVALID_REQUEST", str(exc)) from exc
        if not deleted:
            raise ApiError("NOT_FOUND", "要删除的配置不存在。")
        return self._web_snapshot({}, None)

    @staticmethod
    def _optional_item_id(value):
        if value in (None, ""):
            return None
        try:
            item_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ApiError("INVALID_REQUEST", "配置 ID 无效。") from exc
        if item_id <= 0:
            raise ApiError("INVALID_REQUEST", "配置 ID 无效。")
        return item_id

    @staticmethod
    def _required_item_id(item_id):
        if item_id is None:
            raise ApiError("INVALID_REQUEST", "该操作需要配置 ID。")
        return item_id

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
            show_setting = self.context.state.get("show_gateway_sidebar_status", True)
            status = (count, bool(show_setting and count > 0))
            if status == self._last_sidebar_status:
                return
            self._last_sidebar_status = status
            self.sidebar_widget.set_count(count)
            self.sidebar_widget.setVisible(status[1])

    def _check_cloudflare_process(self):
        for tunnel_id, process in list(self.cloudflare_processes.items()):
            if process and process.poll() is not None:
                self.cloudflare_last_exit_codes[tunnel_id] = process.returncode
                if process.returncode != 0:
                    self.cloudflare_last_errors[tunnel_id] = f"cloudflared exited with code {process.returncode}"
                self.cloudflare_processes.pop(tunnel_id, None)
