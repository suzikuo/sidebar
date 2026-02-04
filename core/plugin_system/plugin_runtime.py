import importlib.util
import os
import sys
from typing import Any, Dict, Type

from core.plugin_system.api_contract import APIContract
from core.plugin_system.event_bus import EventBus
from core.plugin_system.plugin_context import PluginContext
from core.plugin_system.scheduler import PluginScheduler


class PluginRuntime:
    """
    The sandbox executor. Loads plugin code and injects the context.
    Ensures the plugin adheres to permissions and resource limits.
    """

    def __init__(self, event_bus: EventBus, state_store=None):
        self.event_bus = event_bus
        self.state_store = state_store
        self._loaded_plugins: Dict[str, Any] = {}
        self._schedulers: Dict[str, PluginScheduler] = {}

    def load_plugin(self, manifest: Dict[str, Any], plugin_dir: str) -> bool:
        plugin_id = manifest["id"]
        api_version = manifest.get("api_version", "1.0")

        if not APIContract.check_compatibility(api_version):
            print(
                f"Error: Plugin {plugin_id} requires API version {api_version}, which is incompatible with current."
            )
            return False

        # Create Scheduler and Context
        scheduler = PluginScheduler(plugin_id)
        self._schedulers[plugin_id] = scheduler

        context = PluginContext(
            plugin_id=plugin_id,
            scheduler=scheduler,
            event_bus=self.event_bus,
            state_store=self.state_store,
            permissions=manifest.get("permissions", []),
        )

        try:
            # Add plugin directory to sys.path for relative imports
            if plugin_dir not in sys.path:
                sys.path.insert(0, plugin_dir)

            # Load the module
            entry_file = os.path.join(plugin_dir, manifest["entry"])
            spec = importlib.util.spec_from_file_location(
                f"plugin_{plugin_id}", entry_file
            )
            module = importlib.util.module_from_spec(spec)

            # Add to sys.modules to enable relative imports
            sys.modules[f"plugin_{plugin_id}"] = module

            # Sandbox: Prevent module from accessing certain globals if needed (limited in Python)
            # For now, we trust the import but restrict interaction via Context

            spec.loader.exec_module(module)

            # Instantiate the plugin class
            plugin_class: Type = getattr(module, manifest["class"])
            instance = plugin_class(context)

            self._loaded_plugins[plugin_id] = instance
            instance.on_load()

            print(f"Successfully loaded plugin: {plugin_id}")
            return True

        except Exception as e:
            print(f"Failed to load plugin {plugin_id}: {e}")
            import traceback

            traceback.print_exc()
            scheduler.shutdown()
            del self._schedulers[plugin_id]
            return False

    def unload_plugin(self, plugin_id: str):
        if plugin_id in self._loaded_plugins:
            try:
                self._loaded_plugins[plugin_id].on_unload()
            except Exception as e:
                print(f"Error unloading plugin {plugin_id}: {e}")

            del self._loaded_plugins[plugin_id]

        if plugin_id in self._schedulers:
            self._schedulers[plugin_id].shutdown()
            del self._schedulers[plugin_id]

    def get_plugin(self, plugin_id: str) -> Any:
        """Returns the loaded plugin instance or None."""
        return self._loaded_plugins.get(plugin_id)
