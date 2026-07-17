import threading
from typing import Any, Dict

from core.api_gateway import ApiCaller
from core.data_layer.data_service import DataService
from core.data_layer.path_utils import PathManager
from core.logger import logger
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
        api_registry=None,
        capabilities: list = None,
        required_plugins=(),
    ):
        self._plugin_id = plugin_id
        self._scheduler = scheduler
        self._event_bus = event_bus
        self._state_store = state_store
        self._permissions = permissions
        self._api_registry = api_registry
        self._capabilities = frozenset(capabilities or [])
        self._required_plugins = frozenset(required_plugins)
        self._db_instance = None
        self._timers = []
        self._async_tasks = set()
        self._subscription_tokens = set()
        self._resource_lock = threading.RLock()
        self._closed = False

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    # -- Resource Access --

    def create_timer(self):
        with self._resource_lock:
            self._ensure_open()
            timer = self._scheduler.create_timer()
            if timer is not None:
                self._timers.append(timer)
                timer.destroyed.connect(lambda *_: self._discard_timer(timer))
        return timer

    def run_async(self, func, *args, **kwargs):
        with self._resource_lock:
            self._ensure_open()
            task = self._scheduler.run_async(func, *args, **kwargs)
            self._async_tasks.add(task)
            task.add_done_callback(self._discard_async_task)
        return task

    def throttle_ui(self, update_func):
        with self._resource_lock:
            if self._closed:
                return False
        return self._scheduler.request_ui_update(update_func)

    # -- Event Access --

    def publish_event(self, event_type: str, data: Dict[str, Any] = None):
        if "event" not in self._permissions:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not have 'event' permission."
            )
        self._ensure_open()
        self._event_bus.publish(f"plugin.{self._plugin_id}.{event_type}", data)

    def subscribe_event(self, event_type: str, callback):
        if "event" not in self._permissions:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not have 'event' permission."
            )
        with self._resource_lock:
            self._ensure_open()
            token = self._event_bus.subscribe(
                event_type,
                callback,
                owner=self._plugin_id,
            )
            self._subscription_tokens.add(token)
        return token

    # -- Service API Access --

    @property
    def api_registry(self):
        """Host API registry for trusted local UI hosts owned by this plugin."""
        self._ensure_open()
        if self._api_registry is None:
            raise RuntimeError("The application API registry is not available.")
        return self._api_registry

    def register_api_route(
        self,
        action: str,
        handler,
        *,
        version: str = "1.0",
        exported_capability: str = None,
    ):
        if self._api_registry is None:
            raise RuntimeError("The application API registry is not available.")
        self._ensure_open()
        action = str(action or "").strip().strip("/")
        route = f"plugins/{self._plugin_id}/{action}"
        return self._api_registry.register_route(
            self._plugin_id,
            route,
            handler,
            version=version,
            exported_capability=exported_capability,
        )

    def call_api(self, route: str, payload=None, *, expected_version: str = None):
        if self._api_registry is None:
            raise RuntimeError("The application API registry is not available.")
        self._ensure_open()
        caller = ApiCaller.plugin(self._plugin_id, self._capabilities)
        return self._api_registry.call(
            caller,
            route,
            payload,
            expected_version=expected_version,
        )

    def invoke_api(self, route: str, payload=None):
        if self._api_registry is None:
            raise RuntimeError("The application API registry is not available.")
        self._ensure_open()
        caller = ApiCaller.plugin(self._plugin_id, self._capabilities)
        return self._api_registry.invoke(caller, route, payload)

    def call_plugin(
        self,
        plugin_id: str,
        action: str,
        payload=None,
        *,
        version: str = "1.0",
    ):
        """Call a command exported by a declared required plugin."""
        plugin_id = self._ensure_plugin_dependency(plugin_id)
        route = f"plugins/{plugin_id}/{str(action or '').strip().strip('/')}"
        return self.call_api(route, payload, expected_version=version)

    def subscribe_plugin_event(self, plugin_id: str, event: str, callback):
        """Subscribe to an event published by a declared required plugin."""
        plugin_id = self._ensure_plugin_dependency(plugin_id)
        event = str(event or "").strip().strip(".")
        if not event:
            raise ValueError("Plugin event name cannot be empty.")
        return self.subscribe_event(f"plugin.{plugin_id}.{event}", callback)

    # -- Data & State Access (Placeholders for now) --

    @property
    def db(self) -> DataService:
        if "db" not in self._permissions:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not have 'db' permission."
            )

        with self._resource_lock:
            self._ensure_open()
            if self._db_instance is None:
                db_path = PathManager.get_plugin_db_path(self._plugin_id)
                self._db_instance = DataService(db_path)

            return self._db_instance

    @property
    def state(self):
        """Returns a proxy for plugin-specific state management."""

        self._ensure_open()

        class StateProxy:
            def __init__(self, context, store, plugin_id):
                self.context = context
                self.store = store
                self.plugin_id = plugin_id

            def get(self, key: str, default: Any = None) -> Any:
                self.context._ensure_open()
                return self.store.get_plugin_state(self.plugin_id, key, default)

            def set(self, key: str, value: Any):
                self.context._ensure_open()
                self.store.set_plugin_state(self.plugin_id, key, value)

        return StateProxy(self, self._state_store, self._plugin_id)

    def get_data_dir(self) -> str:
        """Returns the plugin's data directory in AppData."""
        self._ensure_open()
        return str(PathManager.get_plugin_data_dir(self._plugin_id))

    def close(self) -> bool:
        """Release resources created through this context. Safe to call repeatedly."""
        with self._resource_lock:
            if self._closed:
                return False
            self._closed = True
            timers = list(self._timers)
            tasks = list(self._async_tasks)
            subscription_tokens = list(self._subscription_tokens)
            db_instance = self._db_instance
            self._timers.clear()
            self._async_tasks.clear()
            self._subscription_tokens.clear()
            self._db_instance = None

        for token in subscription_tokens:
            self._event_bus.unsubscribe_token(token)
        self._event_bus.unsubscribe_owner(self._plugin_id)

        for timer in timers:
            try:
                timer.stop()
                timer.deleteLater()
            except RuntimeError:
                pass

        for task in tasks:
            task.cancel()

        if db_instance is not None:
            try:
                db_instance.close()
            except Exception:
                logger.error(
                    "Failed to close scoped database for plugin %s.",
                    self._plugin_id,
                    exc_info=True,
                )
        return True

    def _ensure_open(self):
        with self._resource_lock:
            if self._closed:
                raise RuntimeError(f"Plugin context is closed: {self._plugin_id}")

    def _ensure_plugin_dependency(self, plugin_id: str):
        plugin_id = str(plugin_id or "").strip()
        if plugin_id not in self._required_plugins:
            raise PermissionError(
                f"Plugin {self._plugin_id} does not declare required plugin {plugin_id}."
            )
        return plugin_id

    def _discard_timer(self, timer):
        with self._resource_lock:
            self._timers = [item for item in self._timers if item is not timer]

    def _discard_async_task(self, task):
        with self._resource_lock:
            self._async_tasks.discard(task)

    def send_notification(self, title: str, message: str, **kwargs):
        """Helper to send a system notification."""
        # Check permissions if strictness is required, but arguably notifications are harmless enough
        # or require a basic 'ui' or 'event' permission.
        # For now, we assume if you have a context, you can notify.
        self._ensure_open()
        data = {"title": title, "message": message}
        data.update(kwargs)
        self._event_bus.publish("system:notification", data)

    def close_detail_view(self):
        """Requests the main application to close any open plugin detail view."""
        self._ensure_open()
        self._event_bus.publish("system:close_detail")

    def open_detail_view(self, plugin_id: str = None):
        """Requests the main application to open a specific plugin detail view."""
        self._ensure_open()
        target_id = plugin_id or self._plugin_id
        self._event_bus.publish("system:open_detail", {"plugin_id": target_id})
