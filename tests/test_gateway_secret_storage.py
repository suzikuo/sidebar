import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from core.security import is_protected_secret
from plugins.gateway_manager.models import GatewayDatabase


class GatewaySecretStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "gateway.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _raw_token(self, table, row_id):
        with closing(sqlite3.connect(self.db_path)) as conn:
            return conn.execute(
                f"SELECT token FROM {table} WHERE id = ?", (row_id,)
            ).fetchone()[0]

    def test_new_tunnel_token_is_encrypted_at_rest(self):
        database = GatewayDatabase(str(self.db_path))
        database.save_cloudflare_tunnel(
            {
                "name": "Test",
                "cloudflared_path": "cloudflared",
                "token": "test-token",
                "gateway_id": None,
                "enabled": True,
                "auto_start": False,
                "remarks": "",
            }
        )
        tunnel = database.list_cloudflare_tunnels()[0]

        self.assertEqual(tunnel["token"], "test-token")
        raw_token = self._raw_token("cloudflare_tunnels", tunnel["id"])
        self.assertTrue(is_protected_secret(raw_token))
        self.assertNotEqual(raw_token, "test-token")

    def test_legacy_plaintext_token_is_migrated_on_open(self):
        GatewayDatabase(str(self.db_path))
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO cloudflare_tunnels
                    (name, cloudflared_path, token, enabled, auto_start, remarks)
                VALUES (?, ?, ?, 1, 0, '')
                """,
                ("Legacy", "cloudflared", "legacy-token"),
            )
            tunnel_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        database = GatewayDatabase(str(self.db_path))
        tunnel = database.get_cloudflare_tunnel(tunnel_id)

        self.assertEqual(tunnel["token"], "legacy-token")
        self.assertTrue(
            is_protected_secret(self._raw_token("cloudflare_tunnels", tunnel_id))
        )


if __name__ == "__main__":
    unittest.main()
