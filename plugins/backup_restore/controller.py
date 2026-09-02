from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal

from .service import BackupArchiveService


class BackupController(QObject):
    backup_created = Signal(object)
    restore_ready = Signal(object)
    error = Signal(str)
    _finished = Signal(str, object)

    def __init__(self, context, service=None, parent=None):
        super().__init__(parent)
        self.context = context
        self.service = service or BackupArchiveService()
        self._busy = False
        self._finished.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

    def create(self, profile, snapshots):
        self._submit("create", self.service.create, profile, snapshots)

    def restore(self, archive_path, destination):
        self._submit("restore", self.service.restore, archive_path, destination)

    def _submit(self, action, callback, *args):
        if self._busy:
            return
        self._busy = True
        try:
            self.context.run_async(self._worker, action, callback, args)
        except Exception:
            self._busy = False
            raise

    def _worker(self, action, callback, args):
        try:
            result = callback(*args)
        except Exception as error:
            result = error
        self._finished.emit(action, result)

    def _deliver(self, action, result):
        self._busy = False
        if isinstance(result, Exception):
            self.error.emit(str(result))
        elif action == "create":
            self.backup_created.emit(result)
        else:
            self.restore_ready.emit(result)


__all__ = ["BackupController"]
