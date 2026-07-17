import copy
import re
from numbers import Real
from typing import Any, Dict

from core.api_gateway import ApiError, ApiRegistry


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
        ]

    def _snapshot(self, payload, context):
        del payload, context
        return copy.deepcopy(self._settings_manager.get_all_settings())

    def _set_setting(self, payload: Dict[str, Any], context):
        del context
        category = payload.get("category")
        key = payload.get("key")
        if not isinstance(category, str) or not isinstance(key, str):
            raise ApiError(
                "INVALID_REQUEST",
                "Setting category and key must be strings.",
            )

        defaults = self._settings_manager.DEFAULTS
        if category not in defaults or key not in defaults[category]:
            raise ApiError("INVALID_REQUEST", "The requested setting is not supported.")
        if "value" not in payload:
            raise ApiError("INVALID_REQUEST", "Setting value is required.")

        value = payload["value"]
        self._validate_value(category, key, value, defaults[category][key])
        self._settings_manager.set_setting(category, key, value)
        return {"category": category, "key": key, "value": value}

    @classmethod
    def _validate_value(cls, category, key, value, default):
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

        enum_values = {
            ("appearance", "theme_mode"): {"light", "dark", "system"},
            ("appearance", "sidebar_position"): {"left", "right"},
            ("appearance", "font_weight"): {"light", "normal", "medium", "bold"},
        }
        allowed = enum_values.get((category, key))
        if allowed is not None and value not in allowed:
            cls._invalid_value()

        numeric_ranges = {
            ("general", "auto_hide_delay"): (0, 10000),
            ("general", "trigger_zone_width"): (1, 50),
            ("appearance", "sidebar_width"): (320, 1200),
            ("appearance", "collapsed_width"): (32, 96),
            ("appearance", "icon_size"): (20, 96),
            ("appearance", "font_size"): (8, 32),
            ("appearance", "peek_width"): (1, 10),
            ("appearance", "sidebar_bg_opacity"): (0.1, 1.0),
            ("appearance", "detail_bg_opacity"): (0.1, 1.0),
            ("appearance", "sidebar_height_percent"): (0.2, 1.0),
            ("appearance", "sidebar_hidden_height_percent"): (0.2, 1.0),
            ("appearance", "sidebar_y_offset"): (-2000, 2000),
        }
        bounds = numeric_ranges.get((category, key))
        if bounds is not None and not bounds[0] <= value <= bounds[1]:
            cls._invalid_value()

        if (category, key) == ("appearance", "accent_color"):
            if not _COLOR_RE.fullmatch(value):
                cls._invalid_value()

    @staticmethod
    def _invalid_value():
        raise ApiError("INVALID_REQUEST", "The setting value is invalid.")
