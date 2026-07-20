__all__ = [
    "SettingsApiService",
    "SettingsCard",
    "SettingsManager",
    "SETTING_SCHEMA",
    "get_public_setting_schema",
]


def __getattr__(name):
    if name == "SettingsApiService":
        from .settings_api import SettingsApiService

        return SettingsApiService
    if name == "SettingsCard":
        from .settings_card import SettingsCard

        return SettingsCard
    if name == "SettingsManager":
        from .settings_manager import SettingsManager

        return SettingsManager
    if name in {"SETTING_SCHEMA", "get_public_setting_schema"}:
        from .settings_schema import SETTING_SCHEMA, get_public_setting_schema

        return {
            "SETTING_SCHEMA": SETTING_SCHEMA,
            "get_public_setting_schema": get_public_setting_schema,
        }[name]
    raise AttributeError(name)
