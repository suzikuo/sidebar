"""Qt background scheduling for the network monitor collector."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from .collector import (
    DEFAULT_CONFIG,
    NetworkMonitorCollector,
    NetworkSnapshot,
    normalize_config,
    validate_config,
)


class NetworkMonitorService(QObject):
    """Schedule collection without blocking the Qt UI thread."""

    snapshot_ready = Signal(object)
    _collection_finished = Signal(object)

    def __init__(self, context, config=None, collector=None, parent=None):
        super().__init__(parent)
        self._context = context
        self._config = normalize_config(config)
        self._collector = collector or NetworkMonitorCollector()
        self._timer = context.create_timer()
        if self._timer is None:
            raise RuntimeError("网络监控无法创建刷新计时器。")
        self._timer.timeout.connect(self.request_refresh)
        self._collection_finished.connect(
            self._deliver_snapshot,
            Qt.ConnectionType.QueuedConnection,
        )
        self._active = False
        self._in_flight = False

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

    def _collect_in_worker(self, config):
        try:
            snapshot = self._collector.collect(config)
        except Exception as error:
            snapshot = NetworkSnapshot(
                system=None,
                proxy=None,
                direct=None,
                v2rayn_enabled=bool(config.get("v2rayn_enabled")),
                v2rayn_connected=False,
                system_error=str(error),
            )
        self._collection_finished.emit(snapshot)

    def _deliver_snapshot(self, snapshot):
        self._in_flight = False
        if self._active:
            self.snapshot_ready.emit(snapshot)

__all__ = [
    "DEFAULT_CONFIG",
    "NetworkMonitorCollector",
    "NetworkMonitorService",
    "NetworkSnapshot",
    "normalize_config",
    "validate_config",
]
