import json
import os
import shutil
import zipfile

from PySide6.QtCore import QObject, Signal

from core.logger import logger
from core.plugin_system.event_bus import EventBus
from core.plugin_system.manifest_loader import ManifestLoader
from core.plugin_system.plugin_runtime import PluginRuntime


class PluginManager(QObject):
    """
    The orchestrator. Discovers plugins on disk and manages their lifecycle
    via the PluginRuntime.
    """

    plugin_loaded = Signal(str, object)  # id, instance
    plugin_unloaded = Signal(str)
    plugin_order_changed = Signal(list)  # new_order

    def __init__(self, plugins_dirs: list[str], event_bus: EventBus, state_store=None):
        super().__init__()
        self.plugins_dirs = plugins_dirs
        self.event_bus = event_bus
        self.state_store = state_store
        self.runtime = PluginRuntime(event_bus, state_store)
        self._manifests = {}
        self._plugin_paths = {}

    def _is_plugin_enabled(self, plugin_id: str) -> bool:
        """Check if a plugin is enabled in settings."""
        if not self.state_store:
            return True  # If no state store, load all plugins

        settings = self.state_store.get("settings", {})
        plugins_settings = settings.get("plugins", {})
        disabled_plugins = plugins_settings.get("disabled", [])

        # Plugin is enabled if it's NOT in the disabled list
        return plugin_id not in disabled_plugins

    def discover_and_load(self):
        """Scans the plugins directories and loads all valid plugins."""
        for plugins_dir in self.plugins_dirs:
            if not os.path.exists(plugins_dir):
                os.makedirs(plugins_dir, exist_ok=True)

            # 1. Discover all plugins in this directory
            for item in os.listdir(plugins_dir):
                item_path = os.path.join(plugins_dir, item)
                if os.path.isdir(item_path):
                    manifest = ManifestLoader.load(item_path)
                    if manifest:
                        plugin_id = manifest["id"]
                        # We might have duplicates across directories, earliest discovery wins
                        if plugin_id not in self._manifests:
                            self._manifests[plugin_id] = manifest
                            self._plugin_paths[plugin_id] = item_path

        # 2. Get load order
        ordered_ids = self.get_plugin_order()

        # 3. Load plugins in order
        for plugin_id in ordered_ids:
            self._load_single_plugin(plugin_id)

    def _load_single_plugin(self, plugin_id):
        """Helper to load a single plugin if enabled."""
        if plugin_id not in self._manifests:
            return

        manifest = self._manifests[plugin_id]
        item_path = self._plugin_paths[plugin_id]

        if self._is_plugin_enabled(plugin_id):
            if self.runtime.load_plugin(manifest, item_path):
                instance = self.runtime._loaded_plugins[plugin_id]
                self.plugin_loaded.emit(plugin_id, instance)
                logger.info(f"Successfully loaded plugin: {plugin_id}")
        else:
            logger.info(f"Plugin {plugin_id} is disabled, skipping load")

    def get_plugin_order(self):
        """Get the defined plugin order, appending new discoveries."""
        if not self.state_store:
            return sorted(self._manifests.keys())

        settings = self.state_store.get("settings", {})
        plugins_settings = settings.get("plugins", {})
        saved_order = plugins_settings.get("order", [])

        # Ensure all discovered plugins are in the list
        all_ids = set(self._manifests.keys())
        current_ids = [pid for pid in saved_order if pid in all_ids]

        # Append any new plugins that weren't in the saved order
        new_ids = all_ids - set(current_ids)
        if new_ids:
            # Sort new IDs to be deterministic
            current_ids.extend(sorted(list(new_ids)))
            # Update state with new complete list
            self.set_plugin_order(current_ids)

        return current_ids

    def set_plugin_order(self, order):
        """Save the plugin order to settings."""
        if self.state_store:
            # We must load current settings, update order, and save back
            # However, state_store.get returns a persistent object usually?
            # The StateStore implementation seems to return dicts. We need to be careful.
            # Let's assume we can update the dict in place via get() reference or need to set it back.
            # Looking at previous code, usage is: self.settings_manager.set_setting(...)
            # But here we have direct access to state_store.

            # Use settings_manager pattern if possible, but we are inside PluginManager.
            # StateStore usually has get/set or direct dict access.

            # Let's try to update via the dict reference chain
            settings = self.state_store.get("settings", {})
            if "plugins" not in settings:
                settings["plugins"] = {}

            settings["plugins"]["order"] = order
            self.state_store.save()

            self.plugin_order_changed.emit(order)

    def reload_plugin(self, plugin_id: str):
        """Reload a specific plugin."""
        if plugin_id in self._manifests:
            logger.info(f"Reloading plugin: {plugin_id}")
            self.runtime.unload_plugin(plugin_id)
            self.plugin_unloaded.emit(plugin_id)

            # Find the path again
            item_path = self._plugin_paths.get(plugin_id)
            if item_path and self.runtime.load_plugin(
                self._manifests[plugin_id], item_path
            ):
                instance = self.runtime._loaded_plugins[plugin_id]
                self.plugin_loaded.emit(plugin_id, instance)

    def refresh_plugin_state(self):
        """Check settings and load/unload plugins accordingly."""
        for plugin_id, manifest in self._manifests.items():
            is_enabled = self._is_plugin_enabled(plugin_id)
            is_loaded = plugin_id in self.runtime._loaded_plugins

            if is_enabled and not is_loaded:
                # Load
                path = self._plugin_paths.get(plugin_id)
                if path and self.runtime.load_plugin(manifest, path):
                    instance = self.runtime._loaded_plugins[plugin_id]
                    self.plugin_loaded.emit(plugin_id, instance)
                    logger.info(f"Enabled and loaded plugin: {plugin_id}")

            elif not is_enabled and is_loaded:
                # Unload
                self.runtime.unload_plugin(plugin_id)
                self.plugin_unloaded.emit(plugin_id)
                logger.info(f"Disabled and unloaded plugin: {plugin_id}")

    def get_all_manifests(self):
        """Return all discovered plugin manifests."""
        return self._manifests

    def get_plugin(self, plugin_id: str):
        """Returns the loaded plugin instance or None."""
        return self.runtime.get_plugin(plugin_id)

    def get_load_errors(self) -> dict:
        """Returns any errors that occurred during plugin loading."""
        return self.runtime.load_errors

    def record_load_error(self, plugin_id: str, error: str):
        """Manually record a load error for a plugin."""
        self.runtime.load_errors[plugin_id] = error

    def install_plugin(self, file_path: str) -> tuple[bool, str]:
        """
        Installs a plugin from a .pyd or .zip file.
        Returns (success, message).
        """
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"

        filename = os.path.basename(file_path)
        name_no_ext, ext = os.path.splitext(filename)
        ext = ext.lower()

        # Target plugins directory (usually the first one)
        if not self.plugins_dirs:
            return False, "No plugin directories configured."

        target_base_dir = self.plugins_dirs[0]

        try:
            if ext == ".pyd":
                # 1. Create directory
                plugin_id = f"{name_no_ext.lower()}_plugin"
                plugin_dir = os.path.join(target_base_dir, plugin_id)
                os.makedirs(plugin_dir, exist_ok=True)

                # 2. Copy .pyd
                target_pyd = os.path.join(plugin_dir, filename)
                shutil.copy2(file_path, target_pyd)

                # 3. Generate manifest.json
                manifest = {
                    "id": plugin_id,
                    "name": name_no_ext.replace("_", " ").title(),
                    "version": "1.0.0",
                    "entry": filename,
                    "class": "Plugin",
                    "api_version": "1.0",
                    "description": f"Auto-generated plugin wrapper for {filename}",
                }

                manifest_path = os.path.join(plugin_dir, "manifest.json")
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=4, ensure_ascii=False)

                logger.info(f"Installed .pyd plugin: {plugin_id}")

            elif ext == ".zip":
                # 1. Extract to temp to check manifest
                import tempfile

                with tempfile.TemporaryDirectory() as tmpdir:
                    with zipfile.ZipFile(file_path, "r") as zip_ref:
                        zip_ref.extractall(tmpdir)

                    # Try to find manifest.json
                    manifest_found = False
                    plugin_id = None

                    # Case A: manifest.json is in root of zip
                    manifest_path = os.path.join(tmpdir, "manifest.json")
                    if os.path.exists(manifest_path):
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            m_data = json.load(f)
                            plugin_id = m_data.get("id")
                            manifest_found = True

                    if not manifest_found:
                        # Case B: zip contains a single folder which contains manifest.json
                        items = os.listdir(tmpdir)
                        if len(items) == 1 and os.path.isdir(
                            os.path.join(tmpdir, items[0])
                        ):
                            inner_manifest = os.path.join(
                                tmpdir, items[0], "manifest.json"
                            )
                            if os.path.exists(inner_manifest):
                                with open(inner_manifest, "r", encoding="utf-8") as f:
                                    m_data = json.load(f)
                                    plugin_id = m_data.get("id")
                                    manifest_found = True

                    if not manifest_found or not plugin_id:
                        return (
                            False,
                            "Invalid plugin zip: manifest.json not found or missing 'id'.",
                        )

                    # 2. Extract for real
                    plugin_dir = os.path.join(target_base_dir, plugin_id)
                    if os.path.exists(plugin_dir):
                        # Simple overwrite? Or error? Let's overwrite but log
                        logger.warning(
                            f"Plugin directory {plugin_dir} already exists, overwriting."
                        )
                        shutil.rmtree(plugin_dir)

                    with zipfile.ZipFile(file_path, "r") as zip_ref:
                        zip_ref.extractall(target_base_dir)

                logger.info(f"Installed .zip plugin: {plugin_id}")
            else:
                return (
                    False,
                    f"Unsupported file type: {ext}. Please provide a .pyd or .zip file.",
                )

            # Refresh and load
            self.discover_and_load()
            return True, f"Plugin {plugin_id} installed successfully!"

        except Exception as e:
            logger.error(f"Failed to install plugin: {e}", exc_info=True)
            return False, f"Installation error: {str(e)}"

    def shutdown(self):
        """Shutdown all loaded plugins."""
        for plugin_id in list(self.runtime._loaded_plugins.keys()):
            self.runtime.unload_plugin(plugin_id)
        logger.info("PluginManager shutdown complete.")
