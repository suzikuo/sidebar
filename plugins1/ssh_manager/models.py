import sqlite3
from contextlib import closing


class DatabaseManager:
    """Repository for SSH connection records."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._create_table()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table(self):
        with closing(self._get_connection()) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ssh_connections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    user TEXT DEFAULT 'root',
                    port INTEGER DEFAULT 22,
                    pem_path TEXT,
                    remarks TEXT,
                    color TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(ssh_connections)").fetchall()
            }
            if "color" not in columns:
                conn.execute("ALTER TABLE ssh_connections ADD COLUMN color TEXT")

    def list_connections(self):
        with closing(self._get_connection()) as conn:
            return conn.execute(
                "SELECT * FROM ssh_connections ORDER BY created_at DESC"
            ).fetchall()

    def get_connection(self, connection_id):
        with closing(self._get_connection()) as conn:
            return conn.execute(
                "SELECT * FROM ssh_connections WHERE id = ?", (connection_id,)
            ).fetchone()

    def create_connection(self, data):
        values = self._connection_values(data)
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.execute(
                """
                INSERT INTO ssh_connections
                    (name, host, user, port, pem_path, remarks, color)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            return cursor.lastrowid

    def update_connection(self, connection_id, data):
        values = self._connection_values(data)
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.execute(
                """
                UPDATE ssh_connections
                SET name=?, host=?, user=?, port=?, pem_path=?, remarks=?, color=?
                WHERE id=?
                """,
                (*values, connection_id),
            )
            return cursor.rowcount > 0

    def delete_connection(self, connection_id):
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.execute(
                "DELETE FROM ssh_connections WHERE id = ?", (connection_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _connection_values(data):
        name = str(data.get("name") or "").strip()
        host = str(data.get("host") or "").strip()
        if not name or not host:
            raise ValueError("SSH connection name and host are required.")

        port = int(data.get("port") or 22)
        if not 1 <= port <= 65535:
            raise ValueError("SSH port must be between 1 and 65535.")

        return (
            name,
            host,
            str(data.get("user") or "root").strip() or "root",
            port,
            str(data.get("pem_path") or "").strip(),
            str(data.get("remarks") or "").strip(),
            data.get("color"),
        )

    def close(self):
        pass
