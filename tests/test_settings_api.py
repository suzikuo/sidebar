import unittest

from core.api_gateway import ApiCaller, ApiRegistry
from core.settings.settings_api import SettingsApiService


class _SettingsManagerStub:
    DEFAULTS = {
        "general": {"enable_notifications": True, "auto_hide_delay": 1000},
        "appearance": {
            "theme_mode": "dark",
            "sidebar_width": 500,
            "sidebar_bg_opacity": 0.9,
            "accent_color": "#FF6B9D",
        },
        "plugins": {"disabled": []},
    }

    def __init__(self):
        self.settings = {
            category: values.copy() for category, values in self.DEFAULTS.items()
        }

    def get_all_settings(self):
        return {category: values.copy() for category, values in self.settings.items()}

    def set_setting(self, category, key, value):
        self.settings[category][key] = value


class SettingsApiServiceTest(unittest.TestCase):
    def setUp(self):
        self.registry = ApiRegistry()
        self.manager = _SettingsManagerStub()
        self.service = SettingsApiService(self.registry, self.manager)
        self.service.register_routes()
        self.reader = ApiCaller.web(
            "settings",
            {SettingsApiService.READ_CAPABILITY},
        )
        self.writer = ApiCaller.web(
            "settings",
            {
                SettingsApiService.READ_CAPABILITY,
                SettingsApiService.WRITE_CAPABILITY,
            },
        )

    def test_snapshot_requires_read_capability_and_is_detached(self):
        denied = self.registry.invoke(
            ApiCaller.web("settings"),
            "core/settings/snapshot",
            {},
        )
        result = self.registry.call(
            self.reader,
            "core/settings/snapshot",
            {},
        )
        result["appearance"]["theme_mode"] = "light"

        self.assertEqual(denied["code"], "FORBIDDEN")
        self.assertEqual(self.manager.settings["appearance"]["theme_mode"], "dark")

    def test_set_validates_capability_type_range_and_known_key(self):
        route = "core/settings/set"
        denied = self.registry.invoke(
            self.reader,
            route,
            {"category": "appearance", "key": "theme_mode", "value": "light"},
        )
        wrong_type = self.registry.invoke(
            self.writer,
            route,
            {"category": "appearance", "key": "sidebar_width", "value": True},
        )
        out_of_range = self.registry.invoke(
            self.writer,
            route,
            {"category": "appearance", "key": "sidebar_width", "value": 200},
        )
        unknown = self.registry.invoke(
            self.writer,
            route,
            {"category": "appearance", "key": "missing", "value": "x"},
        )

        self.assertEqual(denied["code"], "FORBIDDEN")
        self.assertEqual(wrong_type["code"], "INVALID_REQUEST")
        self.assertEqual(out_of_range["code"], "INVALID_REQUEST")
        self.assertEqual(unknown["code"], "INVALID_REQUEST")

    def test_set_updates_valid_setting(self):
        result = self.registry.invoke(
            self.writer,
            "core/settings/set",
            {"category": "appearance", "key": "accent_color", "value": "#112233"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(self.manager.settings["appearance"]["accent_color"], "#112233")


if __name__ == "__main__":
    unittest.main()
