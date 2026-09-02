"""Bounded SQLite time-series storage with deterministic downsampling."""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Iterable

from .history_models import (
    TrafficHistoryPoint,
    TrafficHistoryResult,
    TrafficRankingItem,
    TrafficRecord,
)


SECOND_RETENTION = 60 * 60
MINUTE_RETENTION = 24 * 60 * 60
HOUR_RETENTION = 30 * 24 * 60 * 60
DAY_RETENTION = 365 * 24 * 60 * 60
MAINTENANCE_INTERVAL = 60
MAX_APPLICATIONS_PER_SAMPLE = 128

TABLE_PERIODS = {
    "traffic_second": 1,
    "traffic_minute": 60,
    "traffic_hour": 60 * 60,
    "traffic_day": 24 * 60 * 60,
}

RANGE_CONFIG = {
    "minute": (60, "traffic_second", "second"),
    "hour": (60 * 60, "traffic_second", "second"),
    "today": (None, "traffic_minute", "minute"),
    "7days": (7 * 24 * 60 * 60, "traffic_hour", "hour"),
    "30days": (30 * 24 * 60 * 60, "traffic_hour", "hour"),
    "365days": (365 * 24 * 60 * 60, "traffic_day", "day"),
}


class TrafficHistoryRepository:
    """Store interval byte deltas and retain only bounded time windows."""

    def __init__(self, db_path, clock=time.time):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            str(path),
            timeout=5.0,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._next_maintenance = 0
        self._initialize()

    def close(self):
        with self._lock:
            connection = self._connection
            self._connection = None
            if connection is not None:
                connection.close()

    def submit(self, records: Iterable[TrafficRecord], now=None):
        """Submit source-neutral interval records through one stable interface."""
        normalized = tuple(_normalize_record(record) for record in records)
        normalized = tuple(record for record in normalized if record is not None)
        timestamp = int(self._clock() if now is None else now)
        with self._lock:
            self._ensure_open()
            if normalized:
                with self._connection:
                    self._connection.executemany(_SECOND_UPSERT, normalized)
            if timestamp >= self._next_maintenance:
                self._maintain_locked(timestamp)
                self._next_maintenance = timestamp + MAINTENANCE_INTERVAL

    def query(
        self,
        range_key: str,
        source: str = "system",
        now=None,
        ranking_limit=8,
    ) -> TrafficHistoryResult:
        now = int(self._clock() if now is None else now)
        if range_key not in RANGE_CONFIG:
            raise ValueError(f"不支持的历史范围：{range_key}")
        source = str(source or "system").strip().lower()
        if source not in {"system", "v2ray", "direct", "application"}:
            raise ValueError(f"不支持的流量来源：{source}")
        duration, table, resolution = RANGE_CONFIG[range_key]
        started_at = _local_day_start(now) if duration is None else now - duration
        period = TABLE_PERIODS[table]
        aligned_start = started_at - (started_at % period)
        with self._lock:
            self._ensure_open()
            point_rows = self._connection.execute(
                f"""
                SELECT bucket, SUM(upload_bytes) AS upload_bytes,
                       SUM(download_bytes) AS download_bytes
                FROM {table}
                WHERE source = ? AND bucket >= ? AND bucket <= ?
                GROUP BY bucket
                ORDER BY bucket
                """,
                (source, aligned_start, now),
            ).fetchall()
            ranking_source = "application" if source == "system" else source
            ranking_rows = self._connection.execute(
                f"""
                SELECT app_key, MAX(app_name) AS app_name,
                       MAX(app_path) AS app_path,
                       SUM(upload_bytes) AS upload_bytes,
                       SUM(download_bytes) AS download_bytes
                FROM {table}
                WHERE source = ? AND bucket >= ? AND bucket <= ?
                GROUP BY app_key
                ORDER BY upload_bytes + download_bytes DESC
                LIMIT ?
                """,
                (
                    ranking_source,
                    aligned_start,
                    now,
                    max(1, min(50, int(ranking_limit))),
                ),
            ).fetchall()
        points_by_bucket = {
            int(row["bucket"]): (
                int(row["upload_bytes"] or 0),
                int(row["download_bytes"] or 0),
            )
            for row in point_rows
        }
        points = tuple(
            TrafficHistoryPoint(bucket, *points_by_bucket.get(bucket, (0, 0)))
            for bucket in range(aligned_start, now + 1, period)
        )
        ranking = tuple(
            TrafficRankingItem(
                app_key=row["app_key"],
                app_name=row["app_name"],
                app_path=row["app_path"],
                upload_bytes=int(row["upload_bytes"] or 0),
                download_bytes=int(row["download_bytes"] or 0),
            )
            for row in ranking_rows
        )
        return TrafficHistoryResult(
            range_key=range_key,
            source=source,
            resolution=resolution,
            started_at=started_at,
            ended_at=now,
            points=points,
            ranking=ranking,
            total_upload_bytes=sum(point.upload_bytes for point in points),
            total_download_bytes=sum(point.download_bytes for point in points),
        )

    def maintain(self, now=None):
        timestamp = int(self._clock() if now is None else now)
        with self._lock:
            self._ensure_open()
            self._maintain_locked(timestamp)
            self._next_maintenance = timestamp + MAINTENANCE_INTERVAL

    def row_counts(self) -> dict[str, int]:
        with self._lock:
            self._ensure_open()
            return {
                table: int(
                    self._connection.execute(
                        f"SELECT COUNT(*) FROM {table}"
                    ).fetchone()[0]
                )
                for table in TABLE_PERIODS
            }

    def _initialize(self):
        with self._lock:
            connection = self._connection
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA temp_store=MEMORY")
            connection.execute("PRAGMA busy_timeout=5000")
            with connection:
                for table in TABLE_PERIODS:
                    connection.execute(_CREATE_TABLE.format(table=table))
                    connection.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{table}_source_bucket "
                        f"ON {table}(source, bucket)"
                    )
                    connection.execute(
                        f"CREATE INDEX IF NOT EXISTS idx_{table}_app_bucket "
                        f"ON {table}(app_key, bucket)"
                    )

    def _maintain_locked(self, now):
        closed_minute = now - (now % 60)
        closed_hour = now - (now % (60 * 60))
        closed_day = now - (now % (24 * 60 * 60))
        with self._connection:
            self._rollup_locked(
                "traffic_second", "traffic_minute", 60, closed_minute
            )
            self._rollup_locked(
                "traffic_minute", "traffic_hour", 60 * 60, closed_hour
            )
            self._rollup_locked(
                "traffic_hour", "traffic_day", 24 * 60 * 60, closed_day
            )
            for table, retention in (
                ("traffic_second", SECOND_RETENTION),
                ("traffic_minute", MINUTE_RETENTION),
                ("traffic_hour", HOUR_RETENTION),
                ("traffic_day", DAY_RETENTION),
            ):
                self._connection.execute(
                    f"DELETE FROM {table} WHERE bucket < ?",
                    (now - retention,),
                )
        self._connection.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def _rollup_locked(self, source_table, target_table, period, closed_before):
        source_names = self._connection.execute(
            f"SELECT DISTINCT source FROM {source_table} WHERE bucket < ?",
            (closed_before,),
        ).fetchall()
        for source_row in source_names:
            source = source_row[0]
            source_bounds = self._connection.execute(
                f"""
                SELECT MIN(bucket), MAX(bucket) FROM {source_table}
                WHERE source = ? AND bucket < ?
                """,
                (source, closed_before),
            ).fetchone()
            if source_bounds[0] is None:
                continue
            target_max = self._connection.execute(
                f"SELECT MAX(bucket) FROM {target_table} WHERE source = ?",
                (source,),
            ).fetchone()[0]
            start = int(source_bounds[0]) - (int(source_bounds[0]) % period)
            if target_max is not None:
                start = max(start, int(target_max) + period)
            if start >= closed_before:
                continue
            rows = self._connection.execute(
                f"""
                SELECT (bucket / ?) * ? AS target_bucket,
                       source, app_key, MAX(app_name), MAX(app_path),
                       SUM(upload_bytes), SUM(download_bytes),
                       MAX(peak_upload_bps), MAX(peak_download_bps),
                       SUM(sample_count)
                FROM {source_table}
                WHERE source = ? AND bucket >= ? AND bucket < ?
                GROUP BY target_bucket, source, app_key
                ORDER BY target_bucket
                """,
                (period, period, source, start, closed_before),
            ).fetchall()
            if rows:
                self._connection.executemany(
                    _ROLLUP_REPLACE.format(table=target_table),
                    rows,
                )

    def _ensure_open(self):
        if self._connection is None:
            raise RuntimeError("Traffic history service is closed.")


def _normalize_record(record):
    if not isinstance(record, TrafficRecord):
        raise TypeError("Traffic history records must be TrafficRecord instances.")
    source = str(record.source or "").strip().lower()
    app_key = str(record.app_key or "").strip().casefold()
    if not source or not app_key:
        return None
    upload = max(0, int(record.upload_bytes))
    download = max(0, int(record.download_bytes))
    if upload == 0 and download == 0:
        return None
    normalized = replace(
        record,
        timestamp=int(record.timestamp),
        source=source,
        app_key=app_key,
        app_name=str(record.app_name or app_key),
        app_path=str(record.app_path or ""),
        pid=max(0, int(record.pid)),
        upload_bytes=upload,
        download_bytes=download,
        peak_upload_bps=max(0.0, float(record.peak_upload_bps)),
        peak_download_bps=max(0.0, float(record.peak_download_bps)),
        sample_count=max(1, int(record.sample_count)),
    )
    return (
        normalized.timestamp,
        normalized.source,
        normalized.app_key,
        normalized.app_name,
        normalized.app_path,
        normalized.pid,
        normalized.upload_bytes,
        normalized.download_bytes,
        normalized.peak_upload_bps,
        normalized.peak_download_bps,
        normalized.sample_count,
    )


def _local_day_start(timestamp):
    current = datetime.fromtimestamp(timestamp).astimezone()
    return int(current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS {table} (
    bucket INTEGER NOT NULL,
    source TEXT NOT NULL,
    app_key TEXT NOT NULL,
    app_name TEXT NOT NULL,
    app_path TEXT NOT NULL,
    pid INTEGER NOT NULL DEFAULT 0,
    upload_bytes INTEGER NOT NULL,
    download_bytes INTEGER NOT NULL,
    peak_upload_bps REAL NOT NULL,
    peak_download_bps REAL NOT NULL,
    sample_count INTEGER NOT NULL,
    PRIMARY KEY (bucket, source, app_key, pid)
)
"""

_SECOND_UPSERT = """
INSERT INTO traffic_second (
    bucket, source, app_key, app_name, app_path, pid,
    upload_bytes, download_bytes, peak_upload_bps,
    peak_download_bps, sample_count
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(bucket, source, app_key, pid) DO UPDATE SET
    app_name = excluded.app_name,
    app_path = excluded.app_path,
    upload_bytes = traffic_second.upload_bytes + excluded.upload_bytes,
    download_bytes = traffic_second.download_bytes + excluded.download_bytes,
    peak_upload_bps = MAX(traffic_second.peak_upload_bps, excluded.peak_upload_bps),
    peak_download_bps = MAX(traffic_second.peak_download_bps, excluded.peak_download_bps),
    sample_count = traffic_second.sample_count + excluded.sample_count
"""

_ROLLUP_REPLACE = """
INSERT OR REPLACE INTO {table} (
    bucket, source, app_key, app_name, app_path, pid,
    upload_bytes, download_bytes, peak_upload_bps,
    peak_download_bps, sample_count
) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
"""


TrafficHistoryService = TrafficHistoryRepository


__all__ = [
    "DAY_RETENTION",
    "HOUR_RETENTION",
    "MAX_APPLICATIONS_PER_SAMPLE",
    "MINUTE_RETENTION",
    "RANGE_CONFIG",
    "SECOND_RETENTION",
    "TrafficHistoryRepository",
    "TrafficHistoryService",
]
