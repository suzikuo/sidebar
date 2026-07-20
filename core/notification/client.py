"""Owner-scoped facade exposed to plugin code."""

from __future__ import annotations

from core.notification.models import (
    NotificationAction,
    NotificationLevel,
    NotificationPresentation,
    NotificationProgress,
    NotificationRequest,
    normalize_actions,
)


class PluginNotificationClient:
    def __init__(self, service, owner_id: str):
        self._service = service
        self._owner_id = owner_id

    def show(
        self,
        title: str,
        message: str = "",
        *,
        level: NotificationLevel = NotificationLevel.INFO,
        icon_key: str | None = None,
        duration_ms: int | None = 4000,
        dedupe_key: str | None = None,
        actions: tuple[NotificationAction, ...] | None = None,
        progress: NotificationProgress | None = None,
        sensitive: bool = False,
        presentation: NotificationPresentation = NotificationPresentation.STANDARD,
        transparent_background: bool = False,
    ):
        request = NotificationRequest(
            owner_id=self._owner_id,
            title=title,
            message=message,
            level=level,
            icon_key=icon_key,
            duration_ms=duration_ms,
            dedupe_key=dedupe_key,
            actions=normalize_actions(actions),
            progress=progress,
            sensitive=sensitive,
            presentation=presentation,
            transparent_background=transparent_background,
        )
        return self._service.show(request)

    def update(self, notification_id: str, **changes):
        return self._service.update(self._owner_id, notification_id, **changes)

    def dismiss(self, notification_id: str):
        return self._service.dismiss(self._owner_id, notification_id)
