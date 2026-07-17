import json
import re
from typing import Iterable

from PySide6.QtCore import QObject, Signal, Slot

from core.api_gateway import ApiCaller, ApiRegistry


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


class WebApiBridge(QObject):
    """Restricted JSON transport between a web page and the in-process API gateway."""

    response_ready = Signal(str, str)
    event_ready = Signal(str, str)

    def __init__(
        self,
        registry: ApiRegistry,
        owner_id: str,
        capabilities: Iterable[str] = (),
        *,
        max_payload_bytes: int = 1024 * 1024,
        parent=None,
    ):
        super().__init__(parent)
        if not isinstance(registry, ApiRegistry):
            raise TypeError("WebApiBridge requires an ApiRegistry.")
        if not owner_id or not str(owner_id).strip():
            raise ValueError("Web bridge owner ID is required.")
        if max_payload_bytes <= 0:
            raise ValueError("Web bridge payload limit must be positive.")

        self._registry = registry
        self._caller = ApiCaller.web(str(owner_id).strip(), capabilities)
        self._max_payload_bytes = int(max_payload_bytes)

    @Slot(str, str, str)
    def invoke(self, route: str, payload_json: str, request_id: str):
        if not _REQUEST_ID_RE.fullmatch(request_id or ""):
            self._emit_response(
                request_id,
                self._error("INVALID_REQUEST", "Web request ID is invalid."),
            )
            return

        try:
            payload = self._decode_payload(payload_json)
        except ValueError as exc:
            self._emit_response(
                request_id,
                self._error("INVALID_REQUEST", str(exc)),
            )
            return

        route = str(route or "").strip()
        if not route:
            result = self._error("INVALID_REQUEST", "API route is required.")
        else:
            result = self._registry.invoke(self._caller, route, payload)
        self._emit_response(request_id, result)

    def publish_event(self, event_name: str, payload=None):
        """Emit a host-approved event to JavaScript without exposing EventBus itself."""
        event_name = str(event_name or "").strip()
        if not event_name:
            raise ValueError("Web event name is required.")
        if payload is None:
            payload = {}
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        self.event_ready.emit(event_name, encoded)

    def _decode_payload(self, payload_json: str):
        if not isinstance(payload_json, str):
            raise ValueError("Web API payload must be JSON text.")
        if len(payload_json.encode("utf-8")) > self._max_payload_bytes:
            raise ValueError("Web API payload exceeds the configured size limit.")
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Web API payload is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise ValueError("Web API payload must be a JSON object.")
        return payload

    def _emit_response(self, request_id: str, result):
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        self.response_ready.emit(request_id, encoded)

    @staticmethod
    def _error(code: str, message: str):
        return {"ok": False, "code": code, "message": message}
