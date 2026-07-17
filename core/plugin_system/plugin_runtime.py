import hashlib
import importlib.util
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Type

from core.logger import logger
from core.plugin_system.api_contract import APIContract
from core.plugin_system.event_bus import EventBus
from core.plugin_system.plugin_integrity import purge_plugin_bytecode_caches
from core.plugin_system.plugin_context import PluginContext
from core.plugin_system.scheduler import PluginScheduler


class PluginRuntime:
    """
    The sandbox executor. Loads plugin code and injects the context.
    Ensures the plugin adheres to permissions and resource limits.
    """

    def __init__(self, event_bus: EventBus, state_store=None, api_registry=None):
        self.event_bus = event_bus
        self.state_store = state_store
        self.api_registry = api_registry
        self._loaded_plugins: Dict[str, Any] = {}
        self._contexts: Dict[str, PluginContext] = {}
        self._schedulers: Dict[str, PluginScheduler] = {}
        self._module_names: Dict[str, str] = {}
        self._sys_path_entries: Dict[str, str] = {}
        self._retired_schedulers = []
        self.load_errors: Dict[str, str] = {}

    def load_plugin(self, manifest: Dict[str, Any], plugin_dir: str) -> bool:
        plugin_id = manifest["id"]
        api_version = manifest.get("api_version", "1.0")
        self._reap_retired_schedulers()

        if plugin_id in self._loaded_plugins or plugin_id in self._schedulers:
            err_msg = f"Plugin {plugin_id} is already loaded."
            logger.error(err_msg)
            self.load_errors[plugin_id] = err_msg
            return False

        if not APIContract.check_compatibility(api_version):
            err_msg = f"Plugin {plugin_id} requires API version {api_version}, which is incompatible with current."
            logger.error(err_msg)
            self.load_errors[plugin_id] = err_msg
            return False

        # Create Scheduler and Context
        scheduler = PluginScheduler(plugin_id)
        self._schedulers[plugin_id] = scheduler
        dependencies = manifest.get("dependencies", {})

        context = PluginContext(
            plugin_id=plugin_id,
            scheduler=scheduler,
            event_bus=self.event_bus,
            state_store=self.state_store,
            permissions=manifest.get("permissions", []),
            api_registry=self.api_registry,
            capabilities=manifest.get("capabilities", []),
            required_plugins=(
                dependencies.get("plugins", ())
                if isinstance(dependencies, dict)
                else ()
            ),
        )
        self._contexts[plugin_id] = context
        is_v2_plugin = manifest.get("manifest_version") == 2
        module_prefix = (
            self._v2_module_prefix(plugin_id)
            if is_v2_plugin
            else f"plugin_{plugin_id}"
        )
        self._module_names[plugin_id] = module_prefix
        instance = None

        try:
            purge_plugin_bytecode_caches(plugin_dir)
            entry_file = self._resolve_entry_file(plugin_dir, manifest["entry"])

            if is_v2_plugin:
                module = self._create_v2_entry_module(
                    plugin_id,
                    Path(plugin_dir).resolve(strict=True),
                    entry_file,
                    module_prefix,
                )
            else:
                # Legacy plugins depend on repository-style absolute imports.
                if plugin_dir not in sys.path:
                    sys.path.insert(0, plugin_dir)
                    self._sys_path_entries[plugin_id] = plugin_dir
                spec = importlib.util.spec_from_file_location(
                    module_prefix, entry_file
                )
                if spec is None or spec.loader is None:
                    raise ImportError(
                        f"Cannot create module spec for plugin {plugin_id}."
                    )
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_prefix] = module

            # Sandbox: Prevent module from accessing certain globals if needed (limited in Python)
            # For now, we trust the import but restrict interaction via Context

            previous_bytecode_setting = sys.dont_write_bytecode
            sys.dont_write_bytecode = True
            try:
                if module.__spec__ is None or module.__spec__.loader is None:
                    raise ImportError(
                        f"Cannot create module spec for plugin {plugin_id}."
                    )
                module.__spec__.loader.exec_module(module)
            finally:
                sys.dont_write_bytecode = previous_bytecode_setting

            # Instantiate the plugin class
            plugin_class: Type = getattr(module, manifest["class"])
            instance = plugin_class(context)
            instance.on_load()
            self._loaded_plugins[plugin_id] = instance

            # Clear error if successfully loaded (in case of retry)
            if plugin_id in self.load_errors:
                del self.load_errors[plugin_id]

            logger.info(f"Successfully loaded plugin: {plugin_id}")
            return True

        except Exception as e:
            err_msg = f"Failed to load plugin {plugin_id}: {e}"
            logger.error(err_msg, exc_info=True)
            self.load_errors[plugin_id] = str(e)
            if instance is not None:
                try:
                    instance.on_unload()
                except Exception:
                    logger.error(
                        "Error rolling back partially loaded plugin %s.",
                        plugin_id,
                        exc_info=True,
                    )
            self._loaded_plugins.pop(plugin_id, None)
            self._cleanup_plugin_resources(plugin_id)
            return False

    def unload_plugin(self, plugin_id: str):
        instance = self._loaded_plugins.pop(plugin_id, None)
        if instance is not None:
            try:
                instance.on_unload()
            except Exception as e:
                logger.error(f"Error unloading plugin {plugin_id}: {e}", exc_info=True)

        self._cleanup_plugin_resources(plugin_id)
        self._reap_retired_schedulers()

    def get_plugin(self, plugin_id: str) -> Any:
        """Returns the loaded plugin instance or None."""
        return self._loaded_plugins.get(plugin_id)

    def _cleanup_plugin_resources(self, plugin_id: str):
        context = self._contexts.pop(plugin_id, None)
        if context is not None:
            try:
                context.close()
            except Exception:
                logger.error(
                    "Error closing plugin context for %s.",
                    plugin_id,
                    exc_info=True,
                )

        if self.api_registry:
            try:
                self.api_registry.unregister_owner(plugin_id)
            except Exception:
                logger.error(
                    "Error unregistering API routes for plugin %s.",
                    plugin_id,
                    exc_info=True,
                )

        scheduler = self._schedulers.pop(plugin_id, None)
        if scheduler is not None and not scheduler.shutdown():
            # Keep the wrapper alive until cooperative background work returns.
            self._retired_schedulers.append(scheduler)

        module_prefix = self._module_names.pop(plugin_id, None)
        if module_prefix:
            for module_name in tuple(sys.modules):
                if module_name == module_prefix or module_name.startswith(
                    f"{module_prefix}."
                ):
                    sys.modules.pop(module_name, None)

        plugin_path = self._sys_path_entries.pop(plugin_id, None)
        if plugin_path:
            try:
                sys.path.remove(plugin_path)
            except ValueError:
                pass

    def _reap_retired_schedulers(self):
        self._retired_schedulers = [
            scheduler
            for scheduler in self._retired_schedulers
            if scheduler.active_task_count > 0
        ]

    @staticmethod
    def _v2_module_prefix(plugin_id: str) -> str:
        slug = "".join(
            character if character.isalnum() else "_" for character in plugin_id
        ).strip("_")
        digest = hashlib.sha256(plugin_id.encode("utf-8")).hexdigest()[:12]
        return f"_agiletiles_plugin_{slug or 'plugin'}_{digest}"

    @staticmethod
    def _resolve_entry_file(plugin_dir: str, entry: str) -> Path:
        plugin_root = Path(plugin_dir).resolve(strict=True)
        entry_parts = entry.replace("\\", "/").split("/")
        entry_file = plugin_root.joinpath(*entry_parts).resolve(strict=True)
        try:
            entry_file.relative_to(plugin_root)
        except ValueError as error:
            raise ImportError(
                "Plugin entry resolves outside its plugin directory."
            ) from error
        if not entry_file.is_file():
            raise ImportError("Plugin entry is not a file.")
        return entry_file

    @classmethod
    def _create_v2_entry_module(
        cls,
        plugin_id: str,
        plugin_root: Path,
        entry_file: Path,
        module_prefix: str,
    ) -> ModuleType:
        relative_entry = entry_file.relative_to(plugin_root)
        is_package_entry = relative_entry.name == "__init__.py"
        relative_module_parts = list(relative_entry.with_suffix("").parts)
        if is_package_entry:
            relative_module_parts = relative_module_parts[:-1]

        module_parts = [module_prefix, *relative_module_parts]
        module_name = ".".join(module_parts)
        parent_parts = module_parts[:-1]

        for index in range(1, len(parent_parts) + 1):
            package_name = ".".join(parent_parts[:index])
            relative_parts = parent_parts[1:index]
            package_path = plugin_root.joinpath(*relative_parts)
            cls._install_namespace_package(package_name, package_path)

        search_locations = [str(entry_file.parent)] if is_package_entry else None
        spec = importlib.util.spec_from_file_location(
            module_name,
            entry_file,
            submodule_search_locations=search_locations,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create module spec for plugin {plugin_id}.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        return module

    @staticmethod
    def _install_namespace_package(package_name: str, package_path: Path):
        if package_name in sys.modules:
            raise ImportError(
                f"Plugin module namespace is already in use: {package_name}"
            )
        package = ModuleType(package_name)
        package.__file__ = str(package_path)
        package.__package__ = package_name
        package.__path__ = [str(package_path)]
        package_spec = ModuleSpec(package_name, loader=None, is_package=True)
        package_spec.submodule_search_locations = [str(package_path)]
        package.__spec__ = package_spec
        sys.modules[package_name] = package
