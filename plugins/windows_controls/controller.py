from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from .service import WindowsControlService


class WindowsControlController(QObject):
    snapshot_ready = Signal(object)
    action_finished = Signal(str)
    error = Signal(str)
    _worker_finished = Signal(str, object)

    def __init__(self, context, service=None, parent=None):
        super().__init__(parent)
        self.context = context
        self.service = service or WindowsControlService()
        self._busy = set()
        self._worker_finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def refresh(self):
        self._submit("refresh", self.service.snapshot)

    def perform(self, action, value=None):
        self._submit(action, self.service.perform, action, value)

    def _submit(self, key, callback, *args):
        if key in self._busy:
            return
        self._busy.add(key)
        try:
            self.context.run_async(self._worker, key, callback, args)
        except Exception:
            self._busy.discard(key)
            raise

    def _worker(self, key, callback, args):
        try:
            result = callback(*args)
        except Exception as error:
            result = error
        self._worker_finished.emit(key, result)

    def _deliver(self, key, result):
        self._busy.discard(key)
        if isinstance(result, Exception):
            self.error.emit(str(result))
        elif key == "refresh":
            self.snapshot_ready.emit(result)
        else:
            self.action_finished.emit(key)
            if key in {"brightness", "power_plan"}:
                self.refresh()


__all__ = ["WindowsControlController"]
