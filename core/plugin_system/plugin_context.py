from typing import Any, Dict

from core.data_layer.data_service import DataService
from core.data_layer.path_utils import PathManager
from core.plugin_system.event_bus import EventBus
from core.plugin_system.scheduler import PluginScheduler


class PluginContext:
    """
    The secure proxy object provided to plugins.
    Plugins should ONLY interact with the system through this context.
    """

    def __init__(
        self,
        plugin_id: str,
        scheduler: PluginScheduler,
        event_bus: EventBus,
        state_store,
        permissions: list,
    ):
        self._plugin_id = plugin_id
        self._scheduler = scheduler
        self._event_bus = event_bus
        self._state_store = state_store
        self._permissions = permissions
        self._db_instance = None

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    # -- Resource Access --

    def create_timer(self):
        return self._scheduler.create_timer()

    def run_async(self, func, *args, **kwargs):
        return self._scheduler.run_async(func, *args, **kwargs)

    def throttle_ui(self, update_func):
        return self._scheduler.request_ui_update(update_func)

    # -- Event Access --

    def publish_event(self, event_type: str, data: Dict[str, Any] = None):
        if "event" not in self._permissions:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not have 'event' permission."
            )
        self._event_bus.publish(f"plugin.{self._plugin_id}.{event_type}", data)

    def subscribe_event(self, event_type: str, callback):
        if "event" not in self._permissions:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not have 'event' permission."
            )
        self._event_bus.subscribe(event_type, callback)

    # -- Data & State Access (Placeholders for now) --

    @property
    def db(self) -> DataService:
        if "db" not in self._permissions:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not have 'db' permission."
            )

        if self._db_instance is None:
            db_path = PathManager.get_plugin_db_path(self._plugin_id)
            self._db_instance = DataService(db_path)

        return self._db_instance

    @property
    def state(self):
        """Returns a proxy for plugin-specific state management."""

        class StateProxy:
            def __init__(self, store, plugin_id):
                self.store = store
                self.plugin_id = plugin_id

            def get(self, key: str, default: Any = None) -> Any:
                return self.store.get_plugin_state(self.plugin_id, key, default)

            def set(self, key: str, value: Any):
                self.store.set_plugin_state(self.plugin_id, key, value)

        return StateProxy(self._state_store, self._plugin_id)

    def get_data_dir(self) -> str:
        """Returns the plugin's data directory in AppData."""
        return str(PathManager.get_plugin_data_dir(self._plugin_id))

    def send_notification(self, title: str, message: str, **kwargs):
        """Helper to send a system notification."""
        # Check permissions if strictness is required, but arguably notifications are harmless enough
        # or require a basic 'ui' or 'event' permission.
        # For now, we assume if you have a context, you can notify.
        data = {"title": title, "message": message}
        data.update(kwargs)
        self._event_bus.publish("system:notification", data)

    def close_detail_view(self):
        """Requests the main application to close any open plugin detail view."""
        self._event_bus.publish("system:close_detail")
