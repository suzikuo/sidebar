import json
import os
from typing import Any, Dict

from core.logger import logger


class StateStore:
    """
    Manages persistent UI states and plugin preferences.
    Separates system state from plugin-specific domains.
    """

    def __init__(self, state_file: str):
        self.state_file = state_file
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading state store: {e}", exc_info=True)
        return {"system": {}, "plugins": {}}

    def save(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=4)
        except Exception as e:
            logger.error(f"Error saving state store: {e}", exc_info=True)

    def get_system_state(self, key: str, default: Any = None) -> Any:
        return self._data.get("system", {}).get(key, default)

    def set_system_state(self, key: str, value: Any):
        if "system" not in self._data:
            self._data["system"] = {}
        self._data["system"][key] = value
        self.save()

    def get_plugin_state(self, plugin_id: str, key: str, default: Any = None) -> Any:
        return self._data.get("plugins", {}).get(plugin_id, {}).get(key, default)

    def set_plugin_state(self, plugin_id: str, key: str, value: Any):
        if "plugins" not in self._data:
            self._data["plugins"] = {}
        if plugin_id not in self._data["plugins"]:
            self._data["plugins"][plugin_id] = {}
        self._data["plugins"][plugin_id][key] = value
        self.save()

    def get(self, key: str, default: Any = None) -> Any:
        """Generic get method for any key."""
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        """Generic set method for any key."""
        self._data[key] = value
        self.save()
