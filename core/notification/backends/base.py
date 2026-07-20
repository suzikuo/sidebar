"""Backend contract. Backends never inspect plugin contexts or settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.notification.models import NotificationRequest


@dataclass(frozen=True)
class NotificationCapabilities:
    actions: bool = False
    progress: bool = False
    persistent: bool = False
    sensitive: bool = True


class NotificationBackend(Protocol):
    name: str
    capabilities: NotificationCapabilities

    def is_available(self) -> bool: ...

    def show(self, request: NotificationRequest) -> None: ...

    def update(self, request: NotificationRequest) -> bool: ...

    def dismiss(self, notification_id: str) -> bool: ...

    def shutdown(self) -> None: ...
