import re
from numbers import Real
from typing import Any, Dict

from core.api_gateway import ApiError, ApiRegistry

from .settings_schema import get_public_setting_schema, get_setting_definition


_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PLUGIN_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class SettingsApiService:
    READ_CAPABILITY = "core.settings.read"
    WRITE_CAPABILITY = "core.settings.write"

    def __init__(self, registry: ApiRegistry, settings_manager):
        self._registry = registry
        self._settings_manager = settings_manager

    def register_routes(self):
        return [
            self._registry.register_route(
                "core",
                "core/settings/snapshot",
                self._snapshot,
                exported_capability=self.READ_CAPABILITY,
            ),
            self._registry.register_route(
                "core",
                "core/settings/set",
                self._set_setting,
                exported_capability=self.WRITE_CAPABILITY,
            ),
            self._registry.register_route(
                "core",
                "core/settings/schema",
                self._schema,
                exported_capability=self.READ_CAPABILITY,
            ),
            self._registry.register_route(
                "core",
                "core/settings/batch",
                self._set_batch,
                exported_capability=self.WRITE_CAPABILITY,
            ),
            self._registry.register_route(
                "core",
                "core/settings/reset",
                self._reset,
                exported_capability=self.WRITE_CAPABILITY,
            ),
        ]

    def _snapshot(self, payload, context):
        del payload, context
        return self._settings_manager.get_all_settings()

    def _schema(self, payload, context):
        del payload, context
        return get_public_setting_schema()

    def _set_setting(self, payload: Dict[str, Any], context):
        del context
        category = payload.get("category")
        key = payload.get("key")
        if not isinstance(category, str) or not isinstance(key, str):
            raise ApiError(
                "INVALID_REQUEST",
                "Setting category and key must be strings.",
            )

        definition = get_setting_definition(category, key)
        if definition is None:
            raise ApiError("INVALID_REQUEST", "The requested setting is not supported.")
        if "value" not in payload:
            raise ApiError("INVALID_REQUEST", "Setting value is required.")

        value = payload["value"]
        self._validate_value(category, key, value, definition)
        self._settings_manager.set_setting(category, key, value)
        return {"category": category, "key": key, "value": value}

    def _set_batch(self, payload: Dict[str, Any], context):
        del context
        raw_changes = payload.get("changes")
        if not isinstance(raw_changes, list) or not raw_changes:
            raise ApiError("INVALID_REQUEST", "Settings changes must be a non-empty list.")
        if len(raw_changes) > 128:
            raise ApiError("INVALID_REQUEST", "Too many settings changes were requested.")

        changes = []
        seen = set()
        for raw_change in raw_changes:
            if not isinstance(raw_change, dict):
                raise ApiError("INVALID_REQUEST", "Each setting change must be an object.")
            category = raw_change.get("category")
            key = raw_change.get("key")
            if not isinstance(category, str) or not isinstance(key, str):
                raise ApiError("INVALID_REQUEST", "Setting category and key must be strings.")
            identity = (category, key)
            if identity in seen:
                raise ApiError("INVALID_REQUEST", "Duplicate setting changes are not allowed.")
            seen.add(identity)
            definition = get_setting_definition(category, key)
            if definition is None or "value" not in raw_change:
                raise ApiError("INVALID_REQUEST", "The requested setting is not supported.")
            value = raw_change["value"]
            self._validate_value(category, key, value, definition)
            changes.append((category, key, value))

        self._settings_manager.set_settings_batch(changes)
        return {
            "changes": [
                {"category": category, "key": key, "value": value}
                for category, key, value in changes
            ]
        }

    def _reset(self, payload: Dict[str, Any], context):
        del context
        category = payload.get("category")
        if category is None:
            self._settings_manager.reset_to_defaults()
        elif isinstance(category, str) and category in get_public_setting_schema():
            self._settings_manager.reset_category(category)
        else:
            raise ApiError("INVALID_REQUEST", "The requested setting category is invalid.")
        return self._settings_manager.get_all_settings()

    @classmethod
    def _validate_value(cls, category, key, value, definition):
        default = definition["default"]
        if isinstance(default, bool):
            if not isinstance(value, bool):
                cls._invalid_value()
        elif isinstance(default, int):
            if isinstance(value, bool) or not isinstance(value, int):
                cls._invalid_value()
        elif isinstance(default, float):
            if isinstance(value, bool) or not isinstance(value, Real):
                cls._invalid_value()
            value = float(value)
        elif isinstance(default, str):
            if not isinstance(value, str) or len(value) > 256:
                cls._invalid_value()
        elif isinstance(default, list):
            if not isinstance(value, list):
                cls._invalid_value()
            if any(
                not isinstance(item, str) or not _PLUGIN_ID_RE.fullmatch(item)
                for item in value
            ):
                cls._invalid_value()
        elif not isinstance(value, type(default)):
            cls._invalid_value()

        allowed = {
            option["value"] for option in definition.get("options", ())
        } or None
        if allowed is not None and value not in allowed:
            cls._invalid_value()

        minimum = definition.get("minimum")
        maximum = definition.get("maximum")
        if minimum is not None and value < minimum:
            cls._invalid_value()
        if maximum is not None and value > maximum:
            cls._invalid_value()

        if definition.get("control") == "color":
            if not _COLOR_RE.fullmatch(value):
                cls._invalid_value()

        maximum_length = definition.get("maximumLength")
        if maximum_length is not None and len(value) > maximum_length:
            cls._invalid_value()

    @staticmethod
    def _invalid_value():
        raise ApiError("INVALID_REQUEST", "The setting value is invalid.")
