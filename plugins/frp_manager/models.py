import sqlite3


class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._create_table()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_table(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS frp_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    exe_path TEXT NOT NULL,
                    config_path TEXT NOT NULL,
                    auto_start INTEGER DEFAULT 0,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def execute(self, query, params=()):
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor

    def fetchall(self, query, params=()):
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchall()

    def fetchone(self, query, params=()):
        with self._get_connection() as conn:
            cursor = conn.execute(query, params)
            return cursor.fetchone()

    def close(self):
        pass
