import json
import os
import tempfile
import threading
from typing import Any, Dict

from core.logger import logger


class StateStore:
    """
    Manages persistent UI states and plugin preferences.
    Separates system state from plugin-specific domains.
    """

    def __init__(self, state_file: str):
        self.state_file = state_file
        self._backup_file = f"{state_file}.bak"
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        with self._lock:
            if os.path.exists(self.state_file):
                try:
                    data, _ = self._read_valid_state(self.state_file)
                    return data
                except Exception as e:
                    logger.error(f"Error loading state store: {e}", exc_info=True)

            if os.path.exists(self._backup_file):
                try:
                    data, payload = self._read_valid_state(self._backup_file)
                except Exception as e:
                    logger.error(
                        f"Error loading state store backup: {e}", exc_info=True
                    )
                else:
                    try:
                        self._atomic_write_bytes(self.state_file, payload)
                    except Exception as e:
                        logger.error(
                            f"Error restoring state store backup: {e}",
                            exc_info=True,
                        )
                    else:
                        logger.warning(
                            f"Recovered state store from backup: {self._backup_file}"
                        )
                    return data

            return self._default_data()

    @staticmethod
    def _default_data() -> Dict[str, Any]:
        return {"system": {}, "plugins": {}}

    @staticmethod
    def _read_valid_state(path: str):
        with open(path, "rb") as f:
            payload = f.read()

        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("State store root must be a JSON object")
        return data, payload

    @staticmethod
    def _atomic_write_bytes(target_path: str, payload: bytes):
        directory = os.path.dirname(os.path.abspath(target_path))
        filename = os.path.basename(target_path) or "state"
        descriptor = None
        temp_path = None

        try:
            descriptor, temp_path = tempfile.mkstemp(
                dir=directory,
                prefix=f".{filename}.",
                suffix=".tmp",
            )
            with os.fdopen(descriptor, "wb") as f:
                descriptor = None
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

            os.replace(temp_path, target_path)
            temp_path = None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    logger.error(
                        f"Error cleaning temporary state file: {e}", exc_info=True
                    )

    def _prepare_backup(self) -> bool:
        current_payload = None

        if os.path.exists(self.state_file):
            try:
                _, current_payload = self._read_valid_state(self.state_file)
            except Exception as e:
                logger.error(
                    f"Existing state store is invalid; preserving backup: {e}",
                    exc_info=True,
                )

        if current_payload is not None:
            self._atomic_write_bytes(self._backup_file, current_payload)
            return True

        if os.path.exists(self._backup_file):
            try:
                self._read_valid_state(self._backup_file)
            except Exception as e:
                logger.error(
                    f"Existing state store backup is invalid: {e}", exc_info=True
                )
            else:
                return True

        return False

    def save(self):
        with self._lock:
            try:
                payload = json.dumps(self._data, indent=4).encode("utf-8")
                backup_ready = self._prepare_backup()
                self._atomic_write_bytes(self.state_file, payload)
                if not backup_ready:
                    self._atomic_write_bytes(self._backup_file, payload)
            except Exception as e:
                logger.error(f"Error saving state store: {e}", exc_info=True)

    def get_system_state(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get("system", {}).get(key, default)

    def set_system_state(self, key: str, value: Any):
        with self._lock:
            if "system" not in self._data:
                self._data["system"] = {}
            self._data["system"][key] = value
            self.save()

    def get_plugin_state(self, plugin_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get("plugins", {}).get(plugin_id, {}).get(key, default)

    def set_plugin_state(self, plugin_id: str, key: str, value: Any):
        with self._lock:
            if "plugins" not in self._data:
                self._data["plugins"] = {}
            if plugin_id not in self._data["plugins"]:
                self._data["plugins"][plugin_id] = {}
            self._data["plugins"][plugin_id][key] = value
            self.save()

    def get(self, key: str, default: Any = None) -> Any:
        """Generic get method for any key."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any):
        """Generic set method for any key."""
        with self._lock:
            self._data[key] = value
            self.save()
