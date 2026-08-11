import copy
import json
import os
import tempfile
import threading
import weakref
from typing import Any, Dict

from core.logger import logger


_MISSING = object()


def _flush_store_reference(store_reference):
    store = store_reference()
    if store is not None:
        store._flush_scheduled()


class StateStore:
    """
    Manages persistent UI states and plugin preferences.
    Separates system state from plugin-specific domains.
    """

    DEFAULT_SAVE_DELAY_SECONDS = 0.25

    def __init__(
        self,
        state_file: str,
        *,
        save_delay_seconds: float = DEFAULT_SAVE_DELAY_SECONDS,
    ):
        self.state_file = state_file
        self._backup_file = f"{state_file}.bak"
        self._lock = threading.RLock()
        self._save_delay_seconds = max(0.0, float(save_delay_seconds))
        self._save_timer = None
        self._dirty = False
        self._closed = False
        self._last_payload = None
        self._data: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        with self._lock:
            if os.path.exists(self.state_file):
                try:
                    data, _ = self._read_valid_state(self.state_file)
                    self._last_payload = self._serialize(data)
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
                    self._last_payload = self._serialize(data)
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
    def _serialize(data: Dict[str, Any]) -> bytes:
        return json.dumps(data, indent=4).encode("utf-8")

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

    def save(self) -> bool:
        """Synchronously persist the latest in-memory state."""
        return self.flush()

    def flush(self) -> bool:
        """Cancel a pending save and synchronously persist changed state."""
        with self._lock:
            timer = self._save_timer
            self._save_timer = None
            if timer is not None and timer is not threading.current_thread():
                timer.cancel()
            try:
                payload = self._serialize(self._data)
                if (
                    payload == self._last_payload
                    and os.path.exists(self.state_file)
                ):
                    self._dirty = False
                    return False
                backup_ready = self._prepare_backup()
                self._atomic_write_bytes(self.state_file, payload)
                if not backup_ready:
                    self._atomic_write_bytes(self._backup_file, payload)
                self._last_payload = payload
                self._dirty = False
                return True
            except Exception as e:
                self._dirty = True
                logger.error(f"Error saving state store: {e}", exc_info=True)
                return False

    def close(self) -> bool:
        """Flush pending state and prevent new mutations. Safe to call repeatedly."""
        with self._lock:
            if self._closed:
                return False
            self._closed = True
        self.flush()
        return True

    @property
    def dirty(self) -> bool:
        with self._lock:
            return self._dirty

    def _schedule_save_locked(self):
        self._dirty = True
        if self._save_timer is not None:
            return
        if self._save_delay_seconds == 0:
            self.flush()
            return
        timer = threading.Timer(
            self._save_delay_seconds,
            _flush_store_reference,
            args=(weakref.ref(self),),
        )
        timer.daemon = True
        self._save_timer = timer
        timer.start()

    def _flush_scheduled(self):
        self.flush()

    def _ensure_open_locked(self):
        if self._closed:
            raise RuntimeError("State store is closed")

    def get_system_state(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get("system", {}).get(key, default)

    def set_system_state(self, key: str, value: Any) -> bool:
        with self._lock:
            self._ensure_open_locked()
            if "system" not in self._data:
                self._data["system"] = {}
            if self._data["system"].get(key, _MISSING) == value:
                return False
            self._data["system"][key] = copy.deepcopy(value)
            self._schedule_save_locked()
            return True

    def get_plugin_state(self, plugin_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get("plugins", {}).get(plugin_id, {}).get(key, default)

    def set_plugin_state(self, plugin_id: str, key: str, value: Any) -> bool:
        with self._lock:
            self._ensure_open_locked()
            if "plugins" not in self._data:
                self._data["plugins"] = {}
            if plugin_id not in self._data["plugins"]:
                self._data["plugins"][plugin_id] = {}
            if self._data["plugins"][plugin_id].get(key, _MISSING) == value:
                return False
            self._data["plugins"][plugin_id][key] = copy.deepcopy(value)
            self._schedule_save_locked()
            return True

    def get(self, key: str, default: Any = None) -> Any:
        """Generic get method for any key."""
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        """Generic set method for any key."""
        with self._lock:
            self._ensure_open_locked()
            if self._data.get(key, _MISSING) == value:
                return False
            self._data[key] = copy.deepcopy(value)
            self._schedule_save_locked()
            return True
