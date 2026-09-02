from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from .collector import DiagnosticCollector


class DiagnosticService(QObject):
    snapshot_ready = Signal(object)
    error = Signal(str)
    _finished = Signal(object)

    def __init__(self, context, collector=None, parent=None):
        super().__init__(parent)
        self.context = context
        self.collector = collector or DiagnosticCollector()
        self.timer = context.create_timer()
        if self.timer is None:
            raise RuntimeError("插件诊断无法创建刷新计时器。")
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.refresh)
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)
        self.active = False
        self.in_flight = False

    def start(self):
        if self.active:
            return
        self.active = True
        self.timer.start()
        self.refresh()

    def stop(self):
        self.active = False
        self.timer.stop()

    def refresh(self):
        if not self.active or self.in_flight:
            return
        self.in_flight = True
        self.context.run_async(self._collect)

    def _collect(self):
        try:
            result = self.collector.collect()
        except Exception as error:
            result = error
        self._finished.emit(result)

    def _deliver(self, result):
        self.in_flight = False
        if not self.active:
            return
        if isinstance(result, Exception):
            self.error.emit(str(result))
        else:
            self.snapshot_ready.emit(result)


__all__ = ["DiagnosticService"]
