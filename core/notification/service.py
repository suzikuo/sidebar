"""Thread-safe notification routing and owner lifecycle management."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

from core.logger import logger
from core.notification.models import (
    NotificationRequest,
    NotificationResult,
    NotificationStatus,
)


class NotificationService(QObject):
    """Routes validated requests to configured display backends."""

    _queued_show = Signal(object)
    notification_activated = Signal(str, str)
    notification_action_triggered = Signal(str, str, str)

    def __init__(
        self,
        backends: dict[str, object] | None = None,
        *,
        settings_provider: Callable[[], dict] | None = None,
        default_backend: str = "custom",
        fallback_backends: tuple[str, ...] = (),
        max_pending_per_owner: int = 20,
        parent=None,
    ):
        super().__init__(parent)
        self._backends = dict(backends or {})
        self._settings_provider = settings_provider or (lambda: {})
        self._default_backend = default_backend
        self._fallback_backends = fallback_backends
        self._max_pending_per_owner = max_pending_per_owner
        self._active: dict[str, tuple[NotificationRequest, str]] = {}
        self._dedupe: dict[tuple[str, str], str] = {}
        self._pending: dict[str, deque[NotificationRequest]] = defaultdict(deque)
        self._ready = False
        self._shutdown = False
        self._lock = threading.RLock()
        self._queued_show.connect(self._show_on_main_thread, Qt.QueuedConnection)
        for backend in self._backends.values():
            self._connect_backend_events(backend)

    def set_ready(self):
        with self._lock:
            if self._shutdown:
                return
            self._ready = True
            pending = [item for queue in self._pending.values() for item in queue]
            self._pending.clear()
        for request in pending:
            self._queued_show.emit(request)

    def show(self, request: NotificationRequest) -> NotificationResult:
        with self._lock:
            if self._shutdown:
                return self._result(request, NotificationStatus.FAILED, code="SERVICE_SHUTDOWN")
            if not self._enabled():
                return self._result(request, NotificationStatus.SUPPRESSED, code="NOTIFICATIONS_DISABLED")
            if request.dedupe_key:
                existing_id = self._dedupe.get((request.owner_id, request.dedupe_key))
                if existing_id in self._active:
                    return self.update(request.owner_id, existing_id, **_update_values(request))
            if not self._ready:
                queue = self._pending[request.owner_id]
                if len(queue) >= self._max_pending_per_owner:
                    return self._result(request, NotificationStatus.SUPPRESSED, code="OWNER_QUEUE_FULL")
                queue.append(request)
                return self._result(request, NotificationStatus.QUEUED)
        if threading.current_thread() is threading.main_thread():
            return self._show_now(request)
        self._queued_show.emit(request)
        return self._result(request, NotificationStatus.QUEUED, code="QUEUED_TO_UI_THREAD")

    @Slot(object)
    def _show_on_main_thread(self, request: NotificationRequest):
        self._show_now(request)

    def _show_now(self, request: NotificationRequest) -> NotificationResult:
        with self._lock:
            if self._shutdown:
                return self._result(request, NotificationStatus.FAILED, code="SERVICE_SHUTDOWN")
            if not self._enabled():
                return self._result(request, NotificationStatus.SUPPRESSED, code="NOTIFICATIONS_DISABLED")
            backend = self._find_backend(request)
            if backend is None:
                return self._result(request, NotificationStatus.UNSUPPORTED, code="NO_AVAILABLE_BACKEND")
            try:
                backend.show(request)
            except Exception:
                logger.exception(
                    "Notification delivery failed id=%s owner=%s backend=%s",
                    request.notification_id, request.owner_id, backend.name
                )
                return self._result(request, NotificationStatus.FAILED, backend.name, "BACKEND_FAILURE")
            self._active[request.notification_id] = (request, backend.name)
            if request.dedupe_key:
                self._dedupe[(request.owner_id, request.dedupe_key)] = request.notification_id
            return self._result(request, NotificationStatus.SHOWN, backend.name)

    def update(self, owner_id: str, notification_id: str, **changes) -> NotificationResult:
        with self._lock:
            record = self._active.get(notification_id)
            if record is None:
                return NotificationResult(notification_id, NotificationStatus.FAILED, code="NOTIFICATION_NOT_FOUND")
            request, backend_name = record
            if request.owner_id != owner_id:
                return NotificationResult(notification_id, NotificationStatus.FAILED, code="OWNER_MISMATCH")
            try:
                updated = request.with_updates(**changes)
            except ValueError as error:
                return NotificationResult(notification_id, NotificationStatus.FAILED, backend_name, "INVALID_UPDATE", str(error))
            backend = self._backends.get(backend_name)
            try:
                if backend is None or not backend.update(updated):
                    return NotificationResult(notification_id, NotificationStatus.UNSUPPORTED, backend_name, "UPDATE_UNSUPPORTED")
            except Exception:
                logger.exception("Notification update failed id=%s backend=%s", notification_id, backend_name)
                return NotificationResult(notification_id, NotificationStatus.FAILED, backend_name, "BACKEND_FAILURE")
            self._active[notification_id] = (updated, backend_name)
            return NotificationResult(notification_id, NotificationStatus.SHOWN, backend_name)

    def dismiss(self, owner_id: str, notification_id: str) -> NotificationResult:
        with self._lock:
            record = self._active.get(notification_id)
            if record is None:
                return NotificationResult(notification_id, NotificationStatus.DISMISSED, code="NOTIFICATION_NOT_FOUND")
            request, backend_name = record
            if request.owner_id != owner_id:
                return NotificationResult(notification_id, NotificationStatus.FAILED, code="OWNER_MISMATCH")
            backend = self._backends.get(backend_name)
            try:
                if backend is not None:
                    backend.dismiss(notification_id)
            except Exception:
                logger.exception("Notification dismissal failed id=%s backend=%s", notification_id, backend_name)
                return NotificationResult(notification_id, NotificationStatus.FAILED, backend_name, "BACKEND_FAILURE")
            self._remove_active(request)
            return NotificationResult(notification_id, NotificationStatus.DISMISSED, backend_name)

    def dismiss_owner(self, owner_id: str) -> int:
        with self._lock:
            pending = self._pending.pop(owner_id, ())
            active_ids = [item_id for item_id, (request, _) in self._active.items() if request.owner_id == owner_id]
        for notification_id in active_ids:
            self.dismiss(owner_id, notification_id)
        return len(pending) + len(active_ids)

    def shutdown(self):
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            active = list(self._active.values())
            self._active.clear()
            self._dedupe.clear()
            self._pending.clear()
            backends = tuple(self._backends.values())
        for request, backend_name in active:
            backend = self._backends.get(backend_name)
            if backend is not None:
                try:
                    backend.dismiss(request.notification_id)
                except Exception:
                    logger.exception("Notification cleanup failed id=%s", request.notification_id)
        for backend in backends:
            try:
                backend.shutdown()
            except Exception:
                logger.exception("Notification backend shutdown failed backend=%s", backend.name)

    def _find_backend(self, request: NotificationRequest):
        preferred = self._settings().get("backend", self._default_backend)
        for name in (preferred, *self._fallback_backends):
            backend = self._backends.get(name)
            if backend is not None and backend.is_available() and (not request.sensitive or backend.capabilities.sensitive):
                return backend
        return None

    def _connect_backend_events(self, backend):
        dismissed = getattr(backend, "dismissed", None)
        if callable(getattr(dismissed, "connect", None)):
            dismissed.connect(self._on_backend_dismissed)
        activated = getattr(backend, "activated", None)
        if callable(getattr(activated, "connect", None)):
            activated.connect(self._on_backend_activated)
        action_triggered = getattr(backend, "action_triggered", None)
        if callable(getattr(action_triggered, "connect", None)):
            action_triggered.connect(self._on_backend_action_triggered)

    @Slot(str)
    def _on_backend_dismissed(self, notification_id):
        with self._lock:
            record = self._active.get(notification_id)
            if record is not None:
                self._remove_active(record[0])

    @Slot(str)
    def _on_backend_activated(self, notification_id):
        with self._lock:
            record = self._active.get(notification_id)
        if record is not None:
            self.notification_activated.emit(record[0].owner_id, notification_id)

    @Slot(str, str)
    def _on_backend_action_triggered(self, notification_id, action_id):
        with self._lock:
            record = self._active.get(notification_id)
        if record is None:
            return
        request = record[0]
        if any(action.action_id == action_id for action in request.actions):
            self.notification_action_triggered.emit(request.owner_id, notification_id, action_id)

    def _settings(self) -> dict:
        value = self._settings_provider()
        return value if isinstance(value, dict) else {}

    def _enabled(self) -> bool:
        return bool(self._settings().get("enabled", True))

    def _remove_active(self, request: NotificationRequest):
        self._active.pop(request.notification_id, None)
        if request.dedupe_key:
            self._dedupe.pop((request.owner_id, request.dedupe_key), None)

    @staticmethod
    def _result(request, status, backend=None, code=None, message=None):
        return NotificationResult(request.notification_id, status, backend, code, message)


def _update_values(request: NotificationRequest) -> dict:
    return {
        "title": request.title,
        "message": request.message,
        "level": request.level,
        "icon_key": request.icon_key,
        "duration_ms": request.duration_ms,
        "actions": request.actions,
        "progress": request.progress,
        "sensitive": request.sensitive,
        "presentation": request.presentation,
        "transparent_background": request.transparent_background,
    }
