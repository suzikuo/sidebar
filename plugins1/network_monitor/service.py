"""Qt background scheduling for the network monitor collector."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from core.logger import logger

from .application import EtwApplicationTrafficSource
from .collector import (
    DEFAULT_CONFIG,
    NetworkMonitorCollector,
    NetworkSnapshot,
    normalize_config,
    validate_config,
)
from .records import MinuteHistoryBuffer, snapshot_records
from .v2ray_source import V2RayCollector


class NetworkMonitorService(QObject):
    """Schedule collection without blocking the Qt UI thread."""

    snapshot_ready = Signal(object)
    history_ready = Signal(object)
    _collection_finished = Signal(object)
    _history_finished = Signal(object)

    def __init__(
        self,
        context,
        config=None,
        collector=None,
        application_source=None,
        v2ray_collector=None,
        parent=None,
    ):
        super().__init__(parent)
        self._context = context
        self._config = normalize_config(config)
        self._application_source = application_source or EtwApplicationTrafficSource()
        self._collector = collector or NetworkMonitorCollector(
            application_source=self._application_source
        )
        self._v2ray_collector = v2ray_collector or V2RayCollector()
        self._history_route = f"plugins/{context.plugin_id}"
        self._history_buffer = MinuteHistoryBuffer()
        self._timer = context.create_timer()
        if self._timer is None:
            raise RuntimeError("网络监控无法创建刷新计时器。")
        self._timer.timeout.connect(self.request_refresh)
        self._collection_finished.connect(
            self._deliver_snapshot,
            Qt.ConnectionType.QueuedConnection,
        )
        self._history_finished.connect(
            self._deliver_history,
            Qt.ConnectionType.QueuedConnection,
        )
        self._active = False
        self._in_flight = False
        self._history_in_flight = False
        self._application_started = False

    @property
    def config(self) -> dict:
        return dict(self._config)

    def start(self):
        if self._active:
            return
        self._active = True
        self._timer.start(self._config["refresh_interval_ms"])
        self.request_refresh()

    def stop(self):
        self._active = False
        self._timer.stop()
        self._application_source.stop()
        self._application_started = False
        self._flush_history_buffer()

    def apply_config(self, value):
        self._config = validate_config(value)
        self._timer.setInterval(self._config["refresh_interval_ms"])
        self.request_refresh()

    def request_refresh(self):
        if not self._active or self._in_flight:
            return
        self._in_flight = True
        config = dict(self._config)
        try:
            self._context.run_async(self._collect_in_worker, config)
        except Exception:
            self._in_flight = False
            raise

    def request_history(self, range_key="hour", source="system"):
        if not self._active or self._history_in_flight:
            return False
        self._history_in_flight = True
        try:
            self._context.run_async(self._query_history_in_worker, range_key, source)
        except Exception:
            self._history_in_flight = False
            raise
        return True

    def _collect_in_worker(self, config):
        try:
            application_enabled = config["application_monitor_enabled"]
            if application_enabled and not self._application_started:
                self._application_source.start()
                self._application_started = True
            elif not application_enabled and self._application_started:
                self._application_source.stop()
                self._application_started = False
            v2ray_snapshot = self._v2ray_collector.collect(_v2ray_config(config))
            rates = v2ray_snapshot.rates
            proxy_snapshot = {
                "enabled": v2ray_snapshot.enabled,
                "connected": v2ray_snapshot.connected,
                "uploadSpeed": (
                    None if rates is None else rates.upload_bytes_per_second
                ),
                "downloadSpeed": (
                    None if rates is None else rates.download_bytes_per_second
                ),
                "error": v2ray_snapshot.error,
                "node": v2ray_snapshot.node_name,
                "latencyMs": v2ray_snapshot.latency_ms,
                "route": v2ray_snapshot.route_name,
                "timestamp": v2ray_snapshot.timestamp,
            }
            snapshot = self._collector.collect(config, proxy_snapshot=proxy_snapshot)
        except Exception as error:
            snapshot = NetworkSnapshot(
                system=None,
                proxy=None,
                direct=None,
                v2rayn_enabled=bool(config.get("v2rayn_enabled")),
                v2rayn_connected=False,
                system_error=str(error),
            )
        else:
            try:
                records = snapshot_records(snapshot)
                v2ray_record = _v2ray_history_record(v2ray_snapshot)
                if v2ray_record is not None:
                    records.append(v2ray_record)
                flushed = self._history_buffer.add(records)
                self._submit_history_records(flushed)
            except Exception:
                logger.error("Failed to persist network traffic history.", exc_info=True)
        self._collection_finished.emit(snapshot)

    def _query_history_in_worker(self, range_key, source):
        try:
            result = self._context.call_api(
                f"{self._history_route}/query",
                {"range": range_key, "source": source, "rankingLimit": 8},
                expected_version="1.0",
            )
        except Exception as error:
            result = error
        self._history_finished.emit(result)

    def _deliver_snapshot(self, snapshot):
        self._in_flight = False
        if self._active:
            self.snapshot_ready.emit(snapshot)

    def _deliver_history(self, result):
        self._history_in_flight = False
        if self._active:
            self.history_ready.emit(result)

    def _flush_history_buffer(self):
        try:
            self._submit_history_records(self._history_buffer.flush())
        except Exception:
            logger.error("Failed to flush network traffic history.", exc_info=True)

    def _submit_history_records(self, records):
        if not records:
            return
        self._context.call_api(
            f"{self._history_route}/submit",
            {"records": list(records)},
            expected_version="1.0",
        )


def _v2ray_config(config):
    return {
        "enabled": config.get("v2rayn_enabled", True),
        "host": config.get("v2rayn_host", "127.0.0.1"),
        "metrics_port": config.get("v2rayn_metrics_port", 21193),
        "refresh_interval_ms": config.get("refresh_interval_ms", 1000),
        "timeout_ms": config.get("timeout_ms", 800),
        "show_node": config.get("floating_show_v2ray_metadata", False),
        "show_latency": config.get("floating_show_v2ray_metadata", False),
        "show_route": config.get("floating_show_v2ray_metadata", False),
    }


def _v2ray_history_record(snapshot):
    if snapshot.rates is None or not snapshot.enabled:
        return None
    interval = max(0.001, float(snapshot.interval_seconds))
    return {
        "timestamp": snapshot.timestamp,
        "source": "v2ray",
        "appKey": "__v2ray__",
        "appName": "v2rayN 代理",
        "appPath": "",
        "pid": 0,
        "uploadBytes": round(snapshot.rates.upload_bytes_per_second * interval),
        "downloadBytes": round(snapshot.rates.download_bytes_per_second * interval),
        "peakUploadBps": snapshot.rates.upload_bytes_per_second,
        "peakDownloadBps": snapshot.rates.download_bytes_per_second,
        "sampleCount": 1,
    }

__all__ = [
    "DEFAULT_CONFIG",
    "NetworkMonitorCollector",
    "NetworkMonitorService",
    "NetworkSnapshot",
    "normalize_config",
    "validate_config",
]
