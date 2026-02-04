import sqlite3
from typing import Any, Dict, List


class DataService:
    """
    Unified SQLite interface. Brokered by Runtime to provide scoped
    database access to plugins.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_core_tables()

    def _init_core_tables(self):
        """Internal tables for schema tracking."""
        cursor = self._conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_schema (
                plugin_id TEXT PRIMARY KEY,
                version INTEGER NOT NULL,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.commit()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        self._conn.commit()
        return cursor

    def query_all(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

    def fetchall(self, query: str, params: tuple = ()):
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def fetchone(self, query: str, params: tuple = ()):
        cursor = self._conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()

    def close(self):
        self._conn.close()
