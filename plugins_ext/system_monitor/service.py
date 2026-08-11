from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from .collector import SystemCollector


class SystemMonitorService(QObject):
    snapshot_ready = Signal(object)
    error = Signal(str)
    _collection_finished = Signal(object)

    def __init__(self, context, collector=None, interval_ms=2000, parent=None):
        super().__init__(parent)
        self.context = context
        self.collector = collector or SystemCollector()
        self.interval_ms = max(1000, int(interval_ms))
        self.timer = context.create_timer()
        if self.timer is None:
            raise RuntimeError("系统监控无法创建刷新计时器。")
        self.timer.timeout.connect(self.request_refresh)
        self._collection_finished.connect(
            self._deliver,
            Qt.ConnectionType.QueuedConnection,
        )
        self.active = False
        self.in_flight = False

    def start(self):
        if self.active:
            return
        self.active = True
        self.timer.start(self.interval_ms)
        self.request_refresh()

    def stop(self):
        self.active = False
        self.timer.stop()

    def set_interval(self, interval_ms):
        self.interval_ms = max(1000, int(interval_ms))
        self.timer.setInterval(self.interval_ms)

    def request_refresh(self):
        if not self.active or self.in_flight:
            return
        self.in_flight = True
        try:
            self.context.run_async(self._collect)
        except Exception:
            self.in_flight = False
            raise

    def terminate(self, pid):
        self.collector.terminate(pid)
        self.request_refresh()

    def _collect(self):
        try:
            result = self.collector.collect()
        except Exception as error:
            result = error
        self._collection_finished.emit(result)

    def _deliver(self, result):
        self.in_flight = False
        if not self.active:
            return
        if isinstance(result, Exception):
            self.error.emit(str(result))
        else:
            self.snapshot_ready.emit(result)


__all__ = ["SystemMonitorService"]
