import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.api_gateway import ApiError
from plugins.gateway_manager.models import GatewayDatabase

try:
    from plugins.gateway_manager.plugin import GatewayManagerPlugin
except ImportError:
    GatewayManagerPlugin = None


@unittest.skipUnless(GatewayManagerPlugin, "gateway web API tests require Qt UI dependencies")
class GatewayWebApiTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.plugin = GatewayManagerPlugin.__new__(GatewayManagerPlugin)
        self.plugin.db = GatewayDatabase(str(Path(self.temp_dir.name) / "gateway.db"))
        self.plugin._configuration_snapshot_cache = None
        self.plugin.get_status = lambda: {}
        self.plugin.get_cloudflare_statuses = lambda: {}
        self.plugin.get_logs = lambda: []
        self.plugin.running_count = lambda: 0
        self.plugin.reload_runtime = lambda: True
        self.plugin.is_cloudflare_running = lambda item_id: False
        self.plugin.stop_cloudflare_tunnel = lambda item_id: True
        self.plugin.start_cloudflare_tunnel = lambda item_id: True

    def test_snapshot_redacts_cloudflare_token(self):
        self.plugin.db.save_cloudflare_tunnel(
            {
                "name": "Public tunnel",
                "cloudflared_path": "cloudflared",
                "token": "secret-token",
                "gateway_id": None,
                "enabled": True,
                "auto_start": False,
                "remarks": "",
            }
        )

        tunnel = self.plugin._web_snapshot({}, None)["tunnels"][0]

        self.assertTrue(tunnel["has_token"])
        self.assertNotIn("token", tunnel)
        self.assertNotIn("token", self.plugin._configuration_snapshot_cache["tunnels"][0])

    def test_editing_tunnel_with_blank_token_preserves_existing_secret(self):
        self.plugin.db.save_cloudflare_tunnel(
            {
                "name": "Tunnel",
                "cloudflared_path": "cloudflared",
                "token": "existing-token",
                "gateway_id": None,
                "enabled": True,
                "auto_start": False,
                "remarks": "",
            }
        )
        tunnel_id = self.plugin.db.list_cloudflare_tunnels()[0]["id"]

        self.plugin._web_save(
            {
                "resource": "tunnel",
                "id": tunnel_id,
                "data": {
                    "name": "Renamed",
                    "cloudflared_path": "cloudflared",
                    "token": "",
                    "gateway_id": None,
                    "enabled": True,
                    "auto_start": False,
                    "remarks": "",
                },
            },
            None,
        )

        saved = self.plugin.db.get_cloudflare_tunnel(tunnel_id)
        self.assertEqual(saved["name"], "Renamed")
        self.assertEqual(saved["token"], "existing-token")

    def test_service_save_rejects_non_http_target(self):
        with self.assertRaises(ApiError) as raised:
            self.plugin._web_save(
                {
                    "resource": "service",
                    "data": {
                        "name": "Invalid",
                        "target_url": "file:///tmp/test",
                        "enabled": True,
                    },
                },
                None,
            )

        self.assertEqual(raised.exception.code, "INVALID_REQUEST")

    def test_repeated_snapshot_reuses_configuration_queries(self):
        method_names = (
            "list_gateways",
            "list_cloudflare_tunnels",
            "list_services",
            "list_routes",
        )
        for method_name in method_names:
            original = getattr(self.plugin.db, method_name)
            setattr(self.plugin.db, method_name, MagicMock(wraps=original))

        self.plugin._web_snapshot({}, None)
        self.plugin._web_snapshot({}, None)

        for method_name in method_names:
            getattr(self.plugin.db, method_name).assert_called_once_with()

    def test_save_invalidates_configuration_cache(self):
        first = self.plugin._web_snapshot({}, None)
        self.assertEqual(first["services"], [])

        updated = self.plugin._web_save(
            {
                "resource": "service",
                "data": {
                    "name": "API",
                    "target_url": "http://127.0.0.1:8000",
                    "enabled": True,
                    "remarks": "",
                },
            },
            None,
        )

        self.assertEqual([item["name"] for item in updated["services"]], ["API"])


if __name__ == "__main__":
    unittest.main()
