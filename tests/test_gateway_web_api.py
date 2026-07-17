import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
