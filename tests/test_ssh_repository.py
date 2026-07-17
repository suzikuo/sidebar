import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from plugins.ssh_manager.models import DatabaseManager


class SSHConnectionRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "ssh.db"

    def test_crud_uses_semantic_repository_methods(self):
        repository = DatabaseManager(str(self.db_path))
        connection_id = repository.create_connection(
            {
                "name": "Production",
                "host": "example.com",
                "user": "deploy",
                "port": 2222,
                "pem_path": "deploy.pem",
                "remarks": "Primary",
                "color": "#123456",
            }
        )

        connection = repository.get_connection(connection_id)
        self.assertEqual(connection["name"], "Production")
        self.assertEqual(repository.list_connections()[0]["host"], "example.com")

        updated = repository.update_connection(
            connection_id,
            {
                "name": "Production 2",
                "host": "example.net",
                "user": "root",
                "port": 22,
                "pem_path": "",
                "remarks": "Updated",
                "color": None,
            },
        )
        self.assertTrue(updated)
        self.assertEqual(repository.get_connection(connection_id)["name"], "Production 2")

        self.assertTrue(repository.delete_connection(connection_id))
        self.assertIsNone(repository.get_connection(connection_id))

    def test_legacy_schema_adds_color_column(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE ssh_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    user TEXT DEFAULT 'root',
                    port INTEGER DEFAULT 22,
                    pem_path TEXT,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        DatabaseManager(str(self.db_path))

        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(ssh_connections)")
            }
        self.assertIn("color", columns)

    def test_repository_validates_required_fields_and_port(self):
        repository = DatabaseManager(str(self.db_path))

        with self.assertRaises(ValueError):
            repository.create_connection({"name": "", "host": "example.com"})
        with self.assertRaises(ValueError):
            repository.create_connection(
                {"name": "Invalid", "host": "example.com", "port": 70000}
            )


if __name__ == "__main__":
    unittest.main()
