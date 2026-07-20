"""Typed data contract shared by every notification backend."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable
from uuid import uuid4


class NotificationLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


class NotificationPresentation(str, Enum):
    """Amount of information the in-app toast should display."""

    COMPACT = "compact"
    STANDARD = "standard"
    DETAILED = "detailed"


class NotificationStatus(str, Enum):
    SHOWN = "shown"
    QUEUED = "queued"
    SUPPRESSED = "suppressed"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class NotificationAction:
    action_id: str
    text: str

    def __post_init__(self):
        _validate_identifier("action_id", self.action_id)
        _validate_text("action text", self.text, 48)


@dataclass(frozen=True)
class NotificationProgress:
    value: int
    text: str = ""

    def __post_init__(self):
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise ValueError("progress value must be an integer.")
        if not 0 <= self.value <= 100:
            raise ValueError("progress value must be between 0 and 100.")
        if self.text:
            _validate_text("progress text", self.text, 120)


@dataclass(frozen=True)
class NotificationRequest:
    owner_id: str
    title: str
    message: str
    notification_id: str = field(default_factory=lambda: uuid4().hex)
    level: NotificationLevel = NotificationLevel.INFO
    icon_key: str | None = None
    duration_ms: int | None = 4000
    dedupe_key: str | None = None
    actions: tuple[NotificationAction, ...] = ()
    progress: NotificationProgress | None = None
    sensitive: bool = False
    presentation: NotificationPresentation = NotificationPresentation.STANDARD
    transparent_background: bool = False

    def __post_init__(self):
        _validate_identifier("owner_id", self.owner_id)
        _validate_identifier("notification_id", self.notification_id)
        _validate_text("title", self.title, 120)
        _validate_text("message", self.message, 1000, allow_empty=True)
        if not isinstance(self.level, NotificationLevel):
            raise ValueError("level must be a NotificationLevel.")
        if self.icon_key is not None:
            _validate_identifier("icon_key", self.icon_key)
        if self.duration_ms is not None:
            if not isinstance(self.duration_ms, int) or isinstance(self.duration_ms, bool):
                raise ValueError("duration_ms must be an integer or None.")
            if not 1000 <= self.duration_ms <= 30000:
                raise ValueError("duration_ms must be between 1000 and 30000.")
        if self.dedupe_key is not None:
            _validate_identifier("dedupe_key", self.dedupe_key)
        if len(self.actions) > 3:
            raise ValueError("a notification supports at most three actions.")
        action_ids = [action.action_id for action in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("notification action IDs must be unique.")
        if not isinstance(self.sensitive, bool):
            raise ValueError("sensitive must be a boolean.")
        if not isinstance(self.presentation, NotificationPresentation):
            raise ValueError("presentation must be a NotificationPresentation.")
        if not isinstance(self.transparent_background, bool):
            raise ValueError("transparent_background must be a boolean.")

    def with_updates(self, **changes) -> "NotificationRequest":
        forbidden = {"owner_id", "notification_id"}.intersection(changes)
        if forbidden:
            raise ValueError("owner_id and notification_id cannot be changed.")
        return replace(self, **changes)


@dataclass(frozen=True)
class NotificationResult:
    notification_id: str
    status: NotificationStatus
    backend: str | None = None
    code: str | None = None
    message: str | None = None


def normalize_actions(actions: Iterable[NotificationAction] | None) -> tuple[NotificationAction, ...]:
    return tuple(actions or ())


def _validate_identifier(label: str, value: str):
    if not isinstance(value, str) or not value or len(value) > 96:
        raise ValueError(f"{label} must be a non-empty string no longer than 96 characters.")
    if not all(character.isalnum() or character in "._:-" for character in value):
        raise ValueError(f"{label} contains unsupported characters.")


def _validate_text(label: str, value: str, maximum: int, *, allow_empty: bool = False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{label} must be a non-empty string.")
    if len(value) > maximum:
        raise ValueError(f"{label} must be no longer than {maximum} characters.")
