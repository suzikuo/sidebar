import sqlite3
from urllib.parse import urlparse


class GatewayDatabase:
    def __init__(self, db_path):
        self.db_path = db_path
        self._create_tables()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_tables(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    target_url TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gateways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    listen_host TEXT NOT NULL DEFAULT '127.0.0.1',
                    listen_port INTEGER NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    auto_start INTEGER DEFAULT 0,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(listen_host, listen_port)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS gateway_routes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway_id INTEGER NOT NULL,
                    service_id INTEGER NOT NULL,
                    path_prefix TEXT NOT NULL,
                    preserve_host INTEGER DEFAULT 0,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(gateway_id, path_prefix),
                    FOREIGN KEY(gateway_id) REFERENCES gateways(id) ON DELETE CASCADE,
                    FOREIGN KEY(service_id) REFERENCES services(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cloudflare_tunnel_settings (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cloudflared_path TEXT NOT NULL DEFAULT 'cloudflared',
                    token TEXT,
                    auto_start INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO cloudflare_tunnel_settings
                    (id, cloudflared_path, token, auto_start)
                VALUES
                    (1, 'cloudflared', '', 0)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cloudflare_tunnels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    cloudflared_path TEXT NOT NULL DEFAULT 'cloudflared',
                    token TEXT,
                    gateway_id INTEGER,
                    enabled INTEGER DEFAULT 1,
                    auto_start INTEGER DEFAULT 0,
                    remarks TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(gateway_id) REFERENCES gateways(id) ON DELETE SET NULL
                )
                """
            )
            self._migrate_single_cloudflare_settings(conn)

    def _migrate_single_cloudflare_settings(self, conn):
        existing = conn.execute("SELECT COUNT(*) AS count FROM cloudflare_tunnels").fetchone()
        if existing and existing["count"] > 0:
            return

        legacy = conn.execute(
            """
            SELECT cloudflared_path, token, auto_start
            FROM cloudflare_tunnel_settings
            WHERE id = 1
            """
        ).fetchone()
        if not legacy or not (legacy["token"] or "").strip():
            return

        conn.execute(
            """
            INSERT INTO cloudflare_tunnels
                (name, cloudflared_path, token, gateway_id, enabled, auto_start, remarks)
            VALUES
                (?, ?, ?, NULL, 1, ?, ?)
            """,
            (
                "Default Tunnel",
                legacy["cloudflared_path"] or "cloudflared",
                legacy["token"] or "",
                legacy["auto_start"] or 0,
                "Migrated from single Cloudflare Tunnel settings",
            ),
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

    def list_services(self):
        return self.fetchall("SELECT * FROM services ORDER BY created_at DESC")

    def list_gateways(self):
        return self.fetchall("SELECT * FROM gateways ORDER BY created_at DESC")

    def list_routes(self):
        return self.fetchall(
            """
            SELECT
                r.*,
                g.name AS gateway_name,
                g.listen_host,
                g.listen_port,
                s.name AS service_name,
                s.target_url
            FROM gateway_routes r
            JOIN gateways g ON g.id = r.gateway_id
            JOIN services s ON s.id = r.service_id
            ORDER BY g.listen_port ASC, length(r.path_prefix) DESC, r.path_prefix ASC
            """
        )

    def get_runtime_config(self, auto_only=False):
        gateway_filter = "WHERE g.enabled = 1"
        params = []
        if auto_only:
            gateway_filter += " AND g.auto_start = 1"

        gateways = self.fetchall(
            f"""
            SELECT g.*
            FROM gateways g
            {gateway_filter}
            ORDER BY g.listen_port ASC
            """,
            tuple(params),
        )

        result = []
        for gateway in gateways:
            routes = self.fetchall(
                """
                SELECT
                    r.id,
                    r.path_prefix,
                    r.preserve_host,
                    s.name AS service_name,
                    s.target_url
                FROM gateway_routes r
                JOIN services s ON s.id = r.service_id
                WHERE r.gateway_id = ?
                  AND r.enabled = 1
                  AND s.enabled = 1
                ORDER BY length(r.path_prefix) DESC, r.path_prefix ASC
                """,
                (gateway["id"],),
            )

            result.append(
                {
                    "id": gateway["id"],
                    "name": gateway["name"],
                    "listen_host": gateway["listen_host"],
                    "listen_port": int(gateway["listen_port"]),
                    "routes": [
                        {
                            "id": route["id"],
                            "path_prefix": normalize_path_prefix(route["path_prefix"]),
                            "target_url": route["target_url"],
                            "service_name": route["service_name"],
                            "preserve_host": bool(route["preserve_host"]),
                        }
                        for route in routes
                    ],
                }
            )
        return result

    def get_cloudflare_settings(self):
        row = self.fetchone(
            """
            SELECT cloudflared_path, token, auto_start
            FROM cloudflare_tunnel_settings
            WHERE id = 1
            """
        )
        if not row:
            return {
                "cloudflared_path": "cloudflared",
                "token": "",
                "auto_start": 0,
            }
        return dict(row)

    def save_cloudflare_settings(self, cloudflared_path, token, auto_start):
        self.execute(
            """
            INSERT OR REPLACE INTO cloudflare_tunnel_settings
                (id, cloudflared_path, token, auto_start, updated_at)
            VALUES
                (1, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (cloudflared_path or "cloudflared", token or "", 1 if auto_start else 0),
        )

    def list_cloudflare_tunnels(self):
        return self.fetchall(
            """
            SELECT
                t.*,
                g.name AS gateway_name,
                g.listen_host,
                g.listen_port
            FROM cloudflare_tunnels t
            LEFT JOIN gateways g ON g.id = t.gateway_id
            ORDER BY t.created_at DESC
            """
        )

    def get_cloudflare_tunnel(self, tunnel_id):
        return self.fetchone(
            """
            SELECT *
            FROM cloudflare_tunnels
            WHERE id = ?
            """,
            (tunnel_id,),
        )

    def get_cloudflare_tunnels_for_runtime(self, auto_only=False):
        where = "WHERE enabled = 1"
        if auto_only:
            where += " AND auto_start = 1"
        return [
            dict(row)
            for row in self.fetchall(
                f"""
                SELECT *
                FROM cloudflare_tunnels
                {where}
                ORDER BY created_at DESC
                """
            )
        ]

    def save_cloudflare_tunnel(self, data, tunnel_id=None):
        params = (
            data["name"],
            data.get("cloudflared_path") or "cloudflared",
            data.get("token") or "",
            data.get("gateway_id"),
            1 if data.get("enabled") else 0,
            1 if data.get("auto_start") else 0,
            data.get("remarks") or "",
        )
        if tunnel_id is None:
            self.execute(
                """
                INSERT INTO cloudflare_tunnels
                    (name, cloudflared_path, token, gateway_id, enabled, auto_start, remarks)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
        else:
            self.execute(
                """
                UPDATE cloudflare_tunnels
                SET name=?, cloudflared_path=?, token=?, gateway_id=?, enabled=?, auto_start=?, remarks=?
                WHERE id=?
                """,
                params + (tunnel_id,),
            )

    def delete_cloudflare_tunnel(self, tunnel_id):
        self.execute("DELETE FROM cloudflare_tunnels WHERE id = ?", (tunnel_id,))

    def close(self):
        pass


def normalize_path_prefix(value):
    prefix = (value or "").strip()
    if not prefix:
        prefix = "/"
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    if len(prefix) > 1:
        prefix = prefix.rstrip("/")
    return prefix


def validate_target_url(value):
    parsed = urlparse((value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
