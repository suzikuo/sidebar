"""Capability-scoped API boundary for traffic history persistence."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Mapping

from core.api_gateway import ApiError

from .history_models import TrafficRecord
from .history_repository import TrafficHistoryRepository


class TrafficHistoryApi:
    READ_CAPABILITY = "traffic.history.read"
    WRITE_CAPABILITY = "traffic.history.write"
    WRITE_V2RAY_CAPABILITY = "traffic.history.write.v2ray"
    MAX_RECORDS_PER_REQUEST = 512

    def __init__(self, context, db_path):
        self._context = context
        self._history = TrafficHistoryRepository(Path(db_path))
        self._lock = threading.RLock()
        self._active_calls = 0
        self._close_pending = False

    def register_routes(self):
        return (
            self._context.register_api_route(
                "submit",
                self._submit,
                version="1.0",
                exported_capability=self.WRITE_CAPABILITY,
            ),
            self._context.register_api_route(
                "submit-v2ray",
                self._submit_v2ray,
                version="1.0",
                exported_capability=self.WRITE_V2RAY_CAPABILITY,
            ),
            self._context.register_api_route(
                "query",
                self._query,
                version="1.0",
                exported_capability=self.READ_CAPABILITY,
            ),
            self._context.register_api_route(
                "stats",
                self._stats,
                version="1.0",
                exported_capability=self.READ_CAPABILITY,
            ),
        )

    def close(self):
        with self._lock:
            self._close_pending = True
            self._close_if_idle_locked()

    def _submit(self, payload, request_context):
        del request_context
        return self._with_call(lambda: self._submit_records(payload, None))

    def _submit_v2ray(self, payload, request_context):
        del request_context
        return self._with_call(lambda: self._submit_records(payload, "v2ray"))

    def _submit_records(self, payload, forced_source):
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise ApiError("INVALID_REQUEST", "records 必须是数组。")
        if len(raw_records) > self.MAX_RECORDS_PER_REQUEST:
            raise ApiError("REQUEST_TOO_LARGE", "单次提交的流量记录过多。")
        records = []
        for index, raw in enumerate(raw_records):
            try:
                record = _parse_record(raw, forced_source)
            except (TypeError, ValueError) as error:
                raise ApiError(
                    "INVALID_REQUEST",
                    f"records[{index}] 无效：{error}",
                ) from error
            records.append(record)
        self._history.submit(records)
        return {"accepted": len(records)}

    def _query(self, payload, request_context):
        del request_context

        def run():
            result = self._history.query(
                str(payload.get("range") or "hour"),
                source=str(payload.get("source") or "system"),
                ranking_limit=_bounded_int(payload.get("rankingLimit"), 8, 1, 50),
            )
            return {
                "range": result.range_key,
                "source": result.source,
                "resolution": result.resolution,
                "startedAt": result.started_at,
                "endedAt": result.ended_at,
                "totalUploadBytes": result.total_upload_bytes,
                "totalDownloadBytes": result.total_download_bytes,
                "points": [
                    {
                        "timestamp": point.timestamp,
                        "uploadBytes": point.upload_bytes,
                        "downloadBytes": point.download_bytes,
                    }
                    for point in result.points
                ],
                "ranking": [
                    {
                        "appKey": item.app_key,
                        "appName": item.app_name,
                        "appPath": item.app_path,
                        "uploadBytes": item.upload_bytes,
                        "downloadBytes": item.download_bytes,
                    }
                    for item in result.ranking
                ],
            }

        return self._with_call(run)

    def _stats(self, payload, request_context):
        del payload, request_context
        return self._with_call(lambda: {"rowCounts": self._history.row_counts()})

    def _with_call(self, callback):
        with self._lock:
            if self._history is None or self._close_pending:
                raise ApiError("SERVICE_UNAVAILABLE", "流量历史服务正在关闭。")
            self._active_calls += 1
        try:
            return callback()
        finally:
            with self._lock:
                self._active_calls -= 1
                self._close_if_idle_locked()

    def _close_if_idle_locked(self):
        if not self._close_pending or self._active_calls:
            return
        history = self._history
        self._history = None
        if history is not None:
            history.close()


def serialize_record(record: TrafficRecord) -> dict:
    if not isinstance(record, TrafficRecord):
        raise TypeError("record must be a TrafficRecord")
    return {
        "timestamp": record.timestamp,
        "source": record.source,
        "appKey": record.app_key,
        "appName": record.app_name,
        "appPath": record.app_path,
        "pid": record.pid,
        "uploadBytes": record.upload_bytes,
        "downloadBytes": record.download_bytes,
        "peakUploadBps": record.peak_upload_bps,
        "peakDownloadBps": record.peak_download_bps,
        "sampleCount": record.sample_count,
    }


def _parse_record(value, forced_source=None):
    if not isinstance(value, Mapping):
        raise TypeError("记录必须是对象")
    source = str(forced_source or value.get("source") or "").strip().lower()
    if source not in {"system", "v2ray", "direct", "application"}:
        raise ValueError("source 不受支持")
    return TrafficRecord(
        timestamp=_required_int(value, "timestamp", minimum=0),
        source=source,
        app_key=_required_text(value, "appKey", 1024),
        app_name=_required_text(value, "appName", 260),
        app_path=str(value.get("appPath") or "")[:32768],
        pid=_optional_int(value, "pid", 0, minimum=0),
        upload_bytes=_required_int(value, "uploadBytes", minimum=0),
        download_bytes=_required_int(value, "downloadBytes", minimum=0),
        peak_upload_bps=_optional_float(value, "peakUploadBps", 0.0),
        peak_download_bps=_optional_float(value, "peakDownloadBps", 0.0),
        sample_count=_optional_int(value, "sampleCount", 1, minimum=1),
    )


def _required_text(value, key, maximum):
    parsed = str(value.get(key) or "").strip()
    if not parsed:
        raise ValueError(f"{key} 不能为空")
    if len(parsed) > maximum:
        raise ValueError(f"{key} 过长")
    return parsed


def _required_int(value, key, minimum=None):
    if key not in value or isinstance(value[key], bool):
        raise ValueError(f"{key} 必须是整数")
    parsed = int(value[key])
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{key} 不能小于 {minimum}")
    return parsed


def _optional_int(value, key, default, minimum=None):
    raw = value.get(key, default)
    if isinstance(raw, bool):
        raise ValueError(f"{key} 必须是整数")
    parsed = int(raw)
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{key} 不能小于 {minimum}")
    return parsed


def _optional_float(value, key, default):
    raw = value.get(key, default)
    if isinstance(raw, bool):
        raise ValueError(f"{key} 必须是数字")
    parsed = float(raw)
    if parsed < 0:
        raise ValueError(f"{key} 不能为负数")
    return parsed


def _bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


__all__ = ["TrafficHistoryApi"]
