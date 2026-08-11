"""Backend-independent contract exposed to web UI consumers."""

from __future__ import annotations

from typing import Protocol


class WebViewHost(Protocol):
    load_succeeded: object
    load_failed: object

    def load(self) -> None: ...

    def publish_event(self, event_name: str, payload=None) -> None: ...

    def dispose(self) -> None: ...


__all__ = ["WebViewHost"]
