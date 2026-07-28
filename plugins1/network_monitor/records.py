"""Convert network snapshots to JSON-compatible history API records."""

from __future__ import annotations

from collections import OrderedDict
import threading


MAX_APPLICATIONS_PER_SAMPLE = 128
HISTORY_FLUSH_INTERVAL_SECONDS = 60


class MinuteHistoryBuffer:
    """Coalesce frequent snapshots in memory before a bounded disk write."""

    def __init__(self, interval_seconds=HISTORY_FLUSH_INTERVAL_SECONDS):
        self._interval_seconds = max(1, int(interval_seconds))
        self._bucket_start = None
        self._records = OrderedDict()
        self._lock = threading.RLock()

    def add(self, records):
        records = tuple(record for record in records if isinstance(record, dict))
        if not records:
            return ()
        with self._lock:
            timestamp = max(int(record.get("timestamp", 0)) for record in records)
            bucket_start = timestamp - (timestamp % self._interval_seconds)
            flushed = ()
            if self._bucket_start is None:
                self._bucket_start = bucket_start
            elif bucket_start > self._bucket_start:
                flushed = self.flush()
                self._bucket_start = bucket_start
            for record in records:
                self._merge(record)
            return flushed

    def flush(self):
        with self._lock:
            if self._bucket_start is None or not self._records:
                return ()
            records = []
            for record in self._records.values():
                record = dict(record)
                record["timestamp"] = self._bucket_start
                records.append(record)
            self._records.clear()
            return tuple(records)

    def _merge(self, record):
        key = (str(record.get("source", "")), str(record.get("appKey", "")))
        current = self._records.get(key)
        if current is None:
            self._records[key] = dict(record)
            return
        current["appName"] = record.get("appName", current["appName"])
        current["appPath"] = record.get("appPath", current["appPath"])
        current["pid"] = record.get("pid", current["pid"])
        current["uploadBytes"] += int(record.get("uploadBytes", 0))
        current["downloadBytes"] += int(record.get("downloadBytes", 0))
        current["peakUploadBps"] = max(
            float(current.get("peakUploadBps", 0)),
            float(record.get("peakUploadBps", 0)),
        )
        current["peakDownloadBps"] = max(
            float(current.get("peakDownloadBps", 0)),
            float(record.get("peakDownloadBps", 0)),
        )
        current["sampleCount"] += int(record.get("sampleCount", 1))


def snapshot_records(snapshot):
    interval = max(0.001, float(snapshot.interval_seconds))
    records = []
    for source, name, rates in (
        ("system", "系统总流量", snapshot.system),
        ("direct", "直连（估算）", snapshot.direct),
    ):
        if rates is None:
            continue
        upload_rate = max(0.0, float(rates.upload_bytes_per_second))
        download_rate = max(0.0, float(rates.download_bytes_per_second))
        records.append(
            _record(
                timestamp=snapshot.timestamp,
                source=source,
                app_key=f"__{source}__",
                app_name=name,
                app_path="",
                pid=0,
                upload_bytes=round(upload_rate * interval),
                download_bytes=round(download_rate * interval),
                upload_rate=upload_rate,
                download_rate=download_rate,
            )
        )
    applications = sorted(
        snapshot.applications,
        key=lambda item: item.upload_bytes + item.download_bytes,
        reverse=True,
    )
    for item in applications[:MAX_APPLICATIONS_PER_SAMPLE]:
        if item.upload_bytes <= 0 and item.download_bytes <= 0:
            continue
        records.append(
            _record(
                timestamp=snapshot.timestamp,
                source="application",
                app_key=item.app_key,
                app_name=item.process_name,
                app_path=item.app_path,
                pid=item.pid,
                upload_bytes=item.upload_bytes,
                download_bytes=item.download_bytes,
                upload_rate=item.upload_speed,
                download_rate=item.download_speed,
            )
        )
    remainder = applications[MAX_APPLICATIONS_PER_SAMPLE:]
    if remainder:
        records.append(
            _record(
                timestamp=snapshot.timestamp,
                source="application",
                app_key="__other_apps__",
                app_name="其他应用",
                app_path="",
                pid=0,
                upload_bytes=sum(item.upload_bytes for item in remainder),
                download_bytes=sum(item.download_bytes for item in remainder),
                upload_rate=sum(item.upload_speed for item in remainder),
                download_rate=sum(item.download_speed for item in remainder),
            )
        )
    return records


def _record(
    *,
    timestamp,
    source,
    app_key,
    app_name,
    app_path,
    pid,
    upload_bytes,
    download_bytes,
    upload_rate,
    download_rate,
):
    return {
        "timestamp": int(timestamp),
        "source": source,
        "appKey": app_key,
        "appName": app_name,
        "appPath": app_path,
        "pid": int(pid),
        "uploadBytes": max(0, int(upload_bytes)),
        "downloadBytes": max(0, int(download_bytes)),
        "peakUploadBps": max(0.0, float(upload_rate)),
        "peakDownloadBps": max(0.0, float(download_rate)),
        "sampleCount": 1,
    }


__all__ = [
    "HISTORY_FLUSH_INTERVAL_SECONDS",
    "MAX_APPLICATIONS_PER_SAMPLE",
    "MinuteHistoryBuffer",
    "snapshot_records",
]
