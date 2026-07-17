import inspect
import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from core.logger import logger

from .contracts import ApiCaller, ApiError, ApiRequestContext


_OWNER_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_ROUTE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_VERSION_RE = re.compile(r"^\d+\.\d+$")


@dataclass(frozen=True)
class _Route:
    name: str
    owner_id: str
    handler: Callable[[Dict[str, Any], ApiRequestContext], Any]
    version: str
    exported_capability: Optional[str]


class ApiRegistry:
    """In-process API gateway shared by native UI, web UI, and plugins."""

    def __init__(self):
        self._routes: Dict[str, _Route] = {}
        self._unavailable_routes = set()
        self._lock = threading.RLock()

    def register_route(
        self,
        owner_id: str,
        route: str,
        handler: Callable[[Dict[str, Any], ApiRequestContext], Any],
        *,
        version: str = "1.0",
        exported_capability: str = None,
    ):
        owner_id = self._validate_owner_id(owner_id)
        route = self._validate_route(owner_id, route)
        if not callable(handler):
            raise ValueError("API route handler must be callable.")
        if not _VERSION_RE.fullmatch(str(version or "")):
            raise ValueError("API route version must use major.minor format.")
        if exported_capability is not None:
            exported_capability = str(exported_capability).strip()
            if not exported_capability:
                raise ValueError("Exported capability cannot be empty.")

        with self._lock:
            if route in self._routes:
                raise ValueError(f"API route is already registered: {route}")
            self._routes[route] = _Route(
                name=route,
                owner_id=owner_id,
                handler=handler,
                version=str(version),
                exported_capability=exported_capability,
            )
            self._unavailable_routes.discard(route)
        return route

    def unregister_owner(self, owner_id: str):
        owner_id = self._validate_owner_id(owner_id)
        with self._lock:
            owned_routes = [
                name for name, route in self._routes.items() if route.owner_id == owner_id
            ]
            for name in owned_routes:
                del self._routes[name]
                self._unavailable_routes.add(name)
        return owned_routes

    def call(
        self,
        caller: ApiCaller,
        route: str,
        payload=None,
        *,
        expected_version: str = None,
    ):
        if not isinstance(caller, ApiCaller):
            raise ApiError("INVALID_CALLER", "API caller context is required.")
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping):
            raise ApiError("INVALID_REQUEST", "API payload must be a JSON object.")

        with self._lock:
            route_definition = self._routes.get(route)
            unavailable = route in self._unavailable_routes

        if route_definition is None:
            if unavailable:
                raise ApiError("SERVICE_UNAVAILABLE", f"API route is unavailable: {route}")
            raise ApiError("ROUTE_NOT_FOUND", f"API route was not found: {route}")

        self._authorize(caller, route_definition)
        if expected_version is not None:
            expected_version = str(expected_version)
            if not _VERSION_RE.fullmatch(expected_version):
                raise ApiError(
                    "INVALID_API_VERSION",
                    "Expected API version must use major.minor format.",
                )
            if expected_version.split(".", 1)[0] != route_definition.version.split(
                ".", 1
            )[0]:
                raise ApiError(
                    "INCOMPATIBLE_API_VERSION",
                    f"API route {route} does not support major version {expected_version}.",
                )
        context = ApiRequestContext(
            caller=caller,
            route=route_definition.name,
            version=route_definition.version,
        )
        result = route_definition.handler(dict(payload), context)
        if inspect.isawaitable(result):
            raise ApiError(
                "ASYNC_UNSUPPORTED",
                "Async API handlers require the future async gateway adapter.",
            )
        self._ensure_json_serializable(result)
        return result

    def invoke(
        self,
        caller: ApiCaller,
        route: str,
        payload=None,
        *,
        expected_version: str = None,
    ):
        try:
            data = self.call(
                caller, route, payload, expected_version=expected_version
            )
            return {"ok": True, "data": data}
        except ApiError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message}
        except Exception:
            logger.error("Unhandled API route error: %s", route, exc_info=True)
            return {
                "ok": False,
                "code": "INTERNAL_ERROR",
                "message": "The API route failed unexpectedly.",
            }

    def list_routes(self, caller: ApiCaller):
        with self._lock:
            routes = list(self._routes.values())

        result = []
        for route in routes:
            try:
                self._authorize(caller, route)
            except ApiError:
                continue
            result.append(
                {
                    "route": route.name,
                    "owner": route.owner_id,
                    "version": route.version,
                    "exportedCapability": route.exported_capability,
                }
            )
        return sorted(result, key=lambda item: item["route"])

    @staticmethod
    def _authorize(caller: ApiCaller, route: _Route):
        if caller.kind == "core" or caller.owner_id == route.owner_id:
            return
        capability = route.exported_capability
        if capability and capability in caller.capabilities:
            return
        raise ApiError("FORBIDDEN", f"Caller cannot access API route: {route.name}")

    @staticmethod
    def _validate_owner_id(owner_id: str) -> str:
        owner_id = str(owner_id or "").strip()
        if not _OWNER_ID_RE.fullmatch(owner_id):
            raise ValueError("API route owner ID contains unsupported characters.")
        return owner_id

    @staticmethod
    def _validate_route(owner_id: str, route: str) -> str:
        route = str(route or "").strip().strip("/")
        segments = route.split("/") if route else []
        if not segments or any(not _ROUTE_SEGMENT_RE.fullmatch(part) for part in segments):
            raise ValueError("API route contains unsupported path segments.")

        prefix = "core/" if owner_id == "core" else f"plugins/{owner_id}/"
        if not route.startswith(prefix) or route == prefix.rstrip("/"):
            raise ValueError(f"API route must be namespaced under {prefix}")
        return route

    @staticmethod
    def _ensure_json_serializable(value):
        try:
            json.dumps(value, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ApiError(
                "INVALID_RESPONSE",
                "API route returned a value that is not valid JSON.",
            ) from exc
