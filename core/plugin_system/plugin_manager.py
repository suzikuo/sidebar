import os
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from core.api_gateway import ApiRegistry
from core.data_layer.path_utils import PathManager
from core.logger import logger
from core.plugin_system.event_bus import EventBus
from core.plugin_system.host_environment import build_host_environment
from core.plugin_system.manifest_loader import ManifestLoader
from core.plugin_system.plugin_manifest import (
    HostEnvironment,
    PluginManifestError,
    check_compatibility,
)
from core.plugin_system.plugin_graph import PluginBlockReason, resolve_plugin_graph
from core.plugin_system.plugin_installer import PluginInstaller, PluginInstallerError
from core.plugin_system.plugin_package import is_safe_plugin_id
from core.plugin_system.plugin_runtime import PluginRuntime
from core.plugin_system.plugin_status import PluginStatus, PluginTransactionStatus


_UNCHANGED = object()
_PENDING_CHANGE_STATES = {"pending", "rollback_pending"}


class PluginManager(QObject):
    """
    The orchestrator. Discovers plugins on disk and manages their lifecycle
    via the PluginRuntime.
    """

    plugin_loaded = Signal(str, object)  # id, instance
    plugin_unloaded = Signal(str)
    plugin_order_changed = Signal(list)  # new_order

    def __init__(
        self,
        plugins_dirs: list[str],
        event_bus: EventBus,
        state_store=None,
        api_registry=None,
        user_plugins_dir: str | None = None,
        transaction_root: str | None = None,
        host_environment: HostEnvironment | None = None,
        notification_service=None,
    ):
        super().__init__()
        self.user_plugins_dir = self._normalize_path(
            user_plugins_dir or str(PathManager.get_user_plugins_dir())
        )
        search_paths = self._normalize_search_paths(plugins_dirs)
        self.plugins_dirs = [
            path
            for path in search_paths
            if os.path.normcase(path) != os.path.normcase(self.user_plugins_dir)
        ]
        self.plugins_dirs.append(self.user_plugins_dir)
        self.event_bus = event_bus
        self.state_store = state_store
        self.api_registry = api_registry or ApiRegistry()
        self.runtime = PluginRuntime(
            event_bus,
            state_store,
            self.api_registry,
            notification_service=notification_service,
        )
        self._pending_updates_prepared = False
        self._user_plugins_available = True
        self._update_results = []
        self._manifests = {}
        self._plugin_paths = {}
        self._plugin_sources = {}
        self._plugin_overrides = {}
        self._manifest_models = {}
        self._compatibility_errors = {}
        self._dependency_errors = {}
        self._plugin_graph = None
        self._update_errors = {}
        self._unverified_updates = {}
        self._blocked_user_plugins = set()
        self._restart_required_plugins = set()
        self._host_environment_error = None
        try:
            self.host_environment = host_environment or build_host_environment()
        except PluginManifestError as exc:
            self.host_environment = None
            self._host_environment_error = exc
            self.runtime.load_errors["plugin-host-environment"] = str(exc)
            logger.error("Plugin host environment is unavailable: %s", exc, exc_info=True)
        self._installer_error = None
        try:
            self.installer = PluginInstaller(
                self.user_plugins_dir,
                transaction_root,
                host_environment=self.host_environment,
            )
        except PluginInstallerError as exc:
            self.installer = None
            self._installer_error = exc
            self._pending_updates_prepared = True
            self._user_plugins_available = False
            self.runtime.load_errors["plugin-installer"] = str(exc)
            logger.error(
                "User plugin installer is unavailable; bundled plugins remain enabled: %s",
                exc,
                exc_info=True,
            )

    @staticmethod
    def _normalize_path(path: str) -> str:
        return str(Path(path).resolve()) if path else ""

    @classmethod
    def _normalize_search_paths(cls, paths: list[str]) -> list[str]:
        normalized = []
        seen = set()
        for path in paths:
            resolved = cls._normalize_path(path)
            key = os.path.normcase(resolved)
            if resolved and key not in seen:
                normalized.append(resolved)
                seen.add(key)
        return normalized

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
        if not self._pending_updates_prepared:
            try:
                self.prepare_pending_updates()
            except PluginInstallerError as exc:
                self._user_plugins_available = False
                self.runtime.load_errors["plugin-installer"] = str(exc)
                logger.error(
                    "User plugins disabled because transaction recovery failed: %s",
                    exc,
                    exc_info=True,
                )
        self.discover_plugins()
        if self._plugin_graph is None:
            self._plugin_graph = self._resolve_enabled_plugin_graph()
        self._load_graph_plugins(self._plugin_graph)

    def discover_plugins(self):
        """
        Rebuild the plugin index from low to high priority search roots.

        Later roots override earlier roots. Duplicate ids inside one root are
        resolved deterministically by keeping the first directory name.
        Discovery never creates or modifies bundled roots.
        """
        manifests = {}
        plugin_paths = {}
        plugin_sources = {}
        plugin_overrides = {}
        manifest_models = {}
        compatibility_errors = {}

        for priority, plugins_dir in enumerate(self.plugins_dirs):
            if (
                not self._user_plugins_available
                and os.path.normcase(plugins_dir)
                == os.path.normcase(self.user_plugins_dir)
            ):
                continue
            if not os.path.isdir(plugins_dir):
                continue

            source_kind = (
                "user"
                if os.path.normcase(plugins_dir)
                == os.path.normcase(self.user_plugins_dir)
                else "bundled"
            )
            ids_in_root = set()
            for item in sorted(os.listdir(plugins_dir), key=str.casefold):
                item_path = os.path.join(plugins_dir, item)
                if not os.path.isdir(item_path):
                    continue

                loaded_manifest = ManifestLoader.load_with_model(item_path)
                if not loaded_manifest:
                    continue
                manifest, manifest_model = loaded_manifest

                plugin_id = manifest["id"]
                if source_kind == "user" and item != plugin_id:
                    logger.warning(
                        "Ignoring non-canonical user plugin directory %s for id %s; "
                        "user plugin directories must match their manifest id.",
                        item_path,
                        plugin_id,
                    )
                    continue
                if source_kind == "user" and plugin_id in self._blocked_user_plugins:
                    logger.error(
                        "Skipping user plugin %s because its transaction state is unsafe.",
                        plugin_id,
                    )
                    continue
                if self.host_environment is None:
                    if manifest_model.manifest_version == 2:
                        error = self._host_environment_error
                        compatibility_errors[plugin_id] = {
                            "code": getattr(error, "code", "INVALID_HOST_ENVIRONMENT"),
                            "message": str(error or "Plugin host environment unavailable."),
                            "source": self._normalize_path(item_path),
                        }
                        continue
                else:
                    try:
                        check_compatibility(manifest_model, self.host_environment)
                    except PluginManifestError as exc:
                        compatibility_errors[plugin_id] = {
                            "code": exc.code,
                            "message": str(exc),
                            "source": self._normalize_path(item_path),
                        }
                        logger.warning(
                            "Skipping incompatible plugin %s from %s [%s]: %s",
                            plugin_id,
                            item_path,
                            exc.code,
                            exc,
                        )
                        continue
                if plugin_id in ids_in_root:
                    logger.warning(
                        "Ignoring duplicate plugin id %s in the same source root: %s",
                        plugin_id,
                        item_path,
                    )
                    continue
                ids_in_root.add(plugin_id)

                source = {
                    "kind": source_kind,
                    "path": self._normalize_path(item_path),
                    "search_root": plugins_dir,
                    "priority": priority,
                }
                previous_source = plugin_sources.get(plugin_id)
                if previous_source:
                    plugin_overrides.setdefault(plugin_id, []).append(previous_source)
                    logger.info(
                        "Plugin %s from %s overrides %s",
                        plugin_id,
                        source["path"],
                        previous_source["path"],
                    )

                manifests[plugin_id] = manifest
                manifest_models[plugin_id] = manifest_model
                plugin_paths[plugin_id] = source["path"]
                plugin_sources[plugin_id] = source

        self._manifests = manifests
        self._plugin_paths = plugin_paths
        self._plugin_sources = plugin_sources
        self._plugin_overrides = plugin_overrides
        self._manifest_models = manifest_models
        self._compatibility_errors = compatibility_errors
        self._request_incompatible_update_rollbacks(compatibility_errors)
        self._plugin_graph = self._resolve_enabled_plugin_graph()
        return self.get_all_manifests()

    def _load_single_plugin(self, plugin_id, *, allow_update_recovery=True):
        """Helper to load a single plugin if enabled."""
        static_errors = (
            self._plugin_graph.blocked.get(plugin_id)
            if self._plugin_graph is not None
            else None
        )
        if static_errors:
            logger.warning("Plugin %s is blocked by a required plugin.", plugin_id)
            return False
        unavailable_provider = self._first_unloaded_required_provider(plugin_id)
        if unavailable_provider is not None:
            reason = PluginBlockReason(
                "PLUGIN_DEPENDENCY_LOAD_FAILED",
                unavailable_provider,
                f"Required plugin is not loaded: {unavailable_provider}",
            )
            self._dependency_errors[plugin_id] = (reason,)
            logger.warning(
                "Plugin %s requires unloaded plugin %s.",
                plugin_id,
                unavailable_provider,
            )
            return False
        if plugin_id in self._dependency_errors:
            self._dependency_errors.pop(plugin_id)
        if plugin_id in self._restart_required_plugins:
            logger.warning(
                "Plugin %s will not be loaded again until its queued rollback restarts.",
                plugin_id,
            )
            return False
        if plugin_id not in self._manifests:
            return False

        manifest = self._manifests[plugin_id]
        item_path = self._plugin_paths[plugin_id]

        if self._is_plugin_enabled(plugin_id):
            if self.runtime.load_plugin(manifest, item_path):
                self._mark_update_load_verified(plugin_id, item_path)
                instance = self.runtime._loaded_plugins[plugin_id]
                self.plugin_loaded.emit(plugin_id, instance)
                logger.info(f"Successfully loaded plugin: {plugin_id}")
                return True
            if allow_update_recovery and self._recover_failed_update(
                plugin_id, item_path
            ):
                return self._load_single_plugin(
                    plugin_id, allow_update_recovery=False
                )
        else:
            logger.info(f"Plugin {plugin_id} is disabled, skipping load")
        return False

    def _resolve_enabled_plugin_graph(self):
        preferred_order = self.get_plugin_order()
        enabled_ids = (
            plugin_id
            for plugin_id in preferred_order
            if self._is_plugin_enabled(plugin_id)
        )
        graph = resolve_plugin_graph(
            self._manifest_models,
            enabled_ids,
            preferred_order,
        )
        self._dependency_errors = dict(graph.blocked)
        return graph

    def _load_graph_plugins(self, graph):
        for plugin_id in graph.load_order:
            if (
                plugin_id in self.runtime._loaded_plugins
                or plugin_id in self._dependency_errors
            ):
                continue
            if not self._load_single_plugin(plugin_id):
                self._block_dependents_after_load_failure(graph, plugin_id)

    def _first_unloaded_required_provider(self, plugin_id):
        if self._plugin_graph is None:
            return None
        return next(
            (
                provider_id
                for provider_id, consumers in self._plugin_graph.required_by.items()
                if plugin_id in consumers
                and provider_id not in self.runtime._loaded_plugins
            ),
            None,
        )

    def _block_dependents_after_load_failure(self, graph, failed_plugin_id):
        pending = list(graph.required_by.get(failed_plugin_id, ()))
        seen = set()
        while pending:
            plugin_id = pending.pop(0)
            if plugin_id in seen:
                continue
            seen.add(plugin_id)
            if plugin_id not in graph.load_order:
                continue
            reason = PluginBlockReason(
                "PLUGIN_DEPENDENCY_LOAD_FAILED",
                failed_plugin_id,
                f"Required plugin failed to load: {failed_plugin_id}",
            )
            existing = self._dependency_errors.get(plugin_id, ())
            if reason not in existing:
                self._dependency_errors[plugin_id] = (*existing, reason)
            pending.extend(graph.required_by.get(plugin_id, ()))

    def _preflight_plugin_change(
        self,
        plugin_id,
        replacement=_UNCHANGED,
        *,
        enabled_ids=None,
        check_target=True,
    ):
        current = dict(self._manifest_models)
        preferred_order = tuple(self.get_plugin_order())
        if plugin_id not in preferred_order:
            preferred_order = (*preferred_order, plugin_id)
        current_enabled = {
            item for item in current if self._is_plugin_enabled(item)
        }
        before = resolve_plugin_graph(current, current_enabled, preferred_order)

        proposed = dict(current)
        if replacement is None:
            proposed.pop(plugin_id, None)
        elif replacement is not _UNCHANGED:
            proposed[plugin_id] = replacement
        if enabled_ids is None:
            proposed_enabled = set(current_enabled)
            if (
                replacement is not _UNCHANGED
                and replacement is not None
                and self._is_plugin_enabled(plugin_id)
            ):
                proposed_enabled.add(plugin_id)
        else:
            proposed_enabled = set(enabled_ids)
        proposed_enabled.intersection_update(proposed)

        after = resolve_plugin_graph(proposed, proposed_enabled, preferred_order)
        if check_target and plugin_id in proposed_enabled:
            reasons = after.blocked.get(plugin_id, ())
            if reasons:
                reason = reasons[0]
                raise PluginInstallerError(reason.code, reason.message)

        newly_blocked = []
        for affected_id, reasons in after.blocked.items():
            previous = {
                (reason.code, reason.dependency_id)
                for reason in before.blocked.get(affected_id, ())
            }
            if any(
                (reason.code, reason.dependency_id) not in previous
                for reason in reasons
            ):
                newly_blocked.append(affected_id)
        newly_blocked = sorted(
            (item for item in newly_blocked if item != plugin_id),
            key=lambda item: (
                preferred_order.index(item)
                if item in preferred_order
                else len(preferred_order),
                item,
            ),
        )
        if newly_blocked:
            raise PluginInstallerError(
                "PLUGIN_DEPENDENTS_BLOCKED",
                "Plugin change would block enabled dependents: "
                + ", ".join(newly_blocked),
            )
        return after

    def _ensure_no_pending_plugin_change(self):
        if self.installer is None:
            return
        pending = self.installer.list_transactions(states=_PENDING_CHANGE_STATES)
        if pending:
            active = pending[0]
            raise PluginInstallerError(
                "PLUGIN_CHANGE_PENDING",
                f"Restart or cancel the pending change for {active.plugin_id} first.",
                transaction_id=active.transaction_id,
            )

    def _blocking_dependents(self, plugin_id):
        graph = self._plugin_graph or self._resolve_enabled_plugin_graph()
        pending = list(graph.required_by.get(plugin_id, ()))
        result = []
        seen = set()
        while pending:
            dependent_id = pending.pop(0)
            if dependent_id in seen:
                continue
            seen.add(dependent_id)
            if self._is_plugin_enabled(dependent_id):
                result.append(dependent_id)
            pending.extend(graph.required_by.get(dependent_id, ()))
        return tuple(result)

    def _uninstall_replacement_manifest(self, plugin_id):
        source = self._plugin_sources.get(plugin_id)
        if source is None or source.get("kind") != "user":
            return self._manifest_models.get(plugin_id)
        for candidate in reversed(self._plugin_overrides.get(plugin_id, ())):
            loaded = ManifestLoader.load_with_model(
                candidate["path"],
                log_errors=False,
            )
            if loaded is None:
                continue
            manifest_model = loaded[1]
            if self.host_environment is None:
                if manifest_model.manifest_version == 2:
                    continue
            else:
                try:
                    check_compatibility(manifest_model, self.host_environment)
                except PluginManifestError:
                    continue
            return manifest_model
        return None

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

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> tuple[bool, str]:
        """Persist one enabled state after validating required plugins."""
        if plugin_id not in self._manifest_models:
            return False, f"Plugin is not installed: {plugin_id}"
        if self.state_store is None:
            return False, "Plugin enabled state storage is unavailable."
        if type(enabled) is not bool:
            return False, "Plugin enabled state must be a boolean."

        current_enabled = {
            item for item in self._manifest_models if self._is_plugin_enabled(item)
        }
        if (plugin_id in current_enabled) is enabled:
            return True, f"Plugin {plugin_id} is already {'enabled' if enabled else 'disabled'}."
        proposed_enabled = set(current_enabled)
        if enabled:
            proposed_enabled.add(plugin_id)
        else:
            proposed_enabled.discard(plugin_id)
        try:
            self._ensure_no_pending_plugin_change()
            self._preflight_plugin_change(
                plugin_id,
                enabled_ids=proposed_enabled,
                check_target=enabled,
            )
        except PluginInstallerError as exc:
            return False, f"Plugin state error [{exc.code}]: {exc}"

        settings = self.state_store.get("settings", {})
        plugins_settings = settings.setdefault("plugins", {})
        disabled = set(plugins_settings.get("disabled", ()))
        if enabled:
            disabled.discard(plugin_id)
        else:
            disabled.add(plugin_id)
        plugins_settings["disabled"] = sorted(disabled)
        self.state_store.save()
        self.refresh_plugin_state()
        return True, f"Plugin {plugin_id} was {'enabled' if enabled else 'disabled'}."

    def reload_plugin(self, plugin_id: str):
        """Reload a specific plugin."""
        if plugin_id in self._manifests:
            logger.info(f"Reloading plugin: {plugin_id}")
            self.runtime.unload_plugin(plugin_id)
            self.plugin_unloaded.emit(plugin_id)

            self._load_single_plugin(plugin_id)

    def refresh_plugin_state(self):
        """Check settings and load/unload plugins accordingly."""
        self._plugin_graph = self._resolve_enabled_plugin_graph()
        target_ids = frozenset(self._plugin_graph.load_order)
        for plugin_id in reversed(tuple(self.runtime._loaded_plugins)):
            if plugin_id not in target_ids:
                self.runtime.unload_plugin(plugin_id)
                self.plugin_unloaded.emit(plugin_id)
                logger.info(f"Disabled and unloaded plugin: {plugin_id}")
        self._load_graph_plugins(self._plugin_graph)

    def get_all_manifests(self):
        """Return all discovered plugin manifests."""
        return self._manifests

    def get_plugin_source(self, plugin_id: str):
        """Return detached metadata for the selected plugin source."""
        source = self._plugin_sources.get(plugin_id)
        return deepcopy(source) if source else None

    def get_plugin_overrides(self, plugin_id: str):
        """Return lower-priority sources shadowed by the selected plugin."""
        return deepcopy(self._plugin_overrides.get(plugin_id, []))

    def get_manifest_model(self, plugin_id: str):
        """Return the immutable normalized manifest selected for a plugin."""
        return self._manifest_models.get(plugin_id)

    def get_compatibility_errors(self) -> dict:
        """Return detached errors for candidates skipped before code execution."""
        return deepcopy(self._compatibility_errors)

    def get_dependency_errors(self) -> dict:
        """Return required-plugin errors that prevented code execution."""
        return deepcopy(self._dependency_errors)

    def get_update_errors(self) -> dict:
        """Return detached install/load/rollback failures by plugin id."""
        return deepcopy(self._update_errors)

    def get_plugin_statuses(self) -> tuple[PluginStatus, ...]:
        """Return semantic plugin management state without paths or raw metadata."""

        transactions_by_plugin = {}
        active_transaction_plugin_ids = set()
        visible_transaction_states = {
            "pending",
            "applying",
            "rollback_pending",
            "rolling_back",
            "failed",
        }
        if self.installer is not None:
            all_transactions = self.installer.list_transactions()
            for plugin_id in {item.plugin_id for item in all_transactions}:
                transactions = self.installer.list_transactions(
                    plugin_id=plugin_id
                )
                transactions_by_plugin[plugin_id] = transactions
                if any(
                    item.state in visible_transaction_states for item in transactions
                ):
                    active_transaction_plugin_ids.add(plugin_id)

        plugin_ids = set(self._manifests)
        plugin_ids.update(active_transaction_plugin_ids)
        plugin_ids.update(self._compatibility_errors)
        plugin_ids.update(self._get_user_plugin_ids())
        ordered_ids = [
            plugin_id
            for plugin_id in self.get_plugin_order()
            if plugin_id in plugin_ids
        ]
        ordered_ids.extend(sorted(plugin_ids - set(ordered_ids)))

        statuses = []
        for plugin_id in ordered_ids:
            manifest = self._manifests.get(plugin_id, {})
            source = self._plugin_sources.get(plugin_id, {}).get(
                "kind", "not-installed"
            )
            transactions = transactions_by_plugin.get(plugin_id, [])
            latest = next(
                (
                    item
                    for item in transactions
                    if item.state in visible_transaction_states
                ),
                None,
            )
            rollback_candidate = self._find_rollback_candidate(transactions)
            user_present, user_version = self._get_user_plugin_state(plugin_id)
            update_error = self._update_errors.get(plugin_id, {}).get("message")
            compatibility_error = self._compatibility_errors.get(plugin_id, {}).get(
                "message"
            )
            dependency_reasons = self._dependency_errors.get(plugin_id, ())
            blocked_reason = dependency_reasons[0] if dependency_reasons else None
            transaction_blocks_changes = latest is not None and latest.state in {
                "pending",
                "applying",
                "rollback_pending",
                "rolling_back",
                "failed",
            }
            transaction_status = (
                PluginTransactionStatus(
                    operation=latest.operation,
                    state=latest.state,
                    version=latest.version,
                    generation=latest.generation,
                    load_verified=latest.load_verified,
                    error_code=latest.error_code,
                    error_message=latest.error_message,
                )
                if latest
                else None
            )
            uninstall_dependency_safe = True
            blocking_dependents = self._blocking_dependents(plugin_id)
            if user_present:
                try:
                    self._preflight_plugin_change(
                        plugin_id,
                        self._uninstall_replacement_manifest(plugin_id),
                        check_target=False,
                    )
                except PluginInstallerError:
                    uninstall_dependency_safe = False
            statuses.append(
                PluginStatus(
                    plugin_id=plugin_id,
                    name=manifest.get("name", plugin_id),
                    selected_version=manifest.get("version"),
                    source=source,
                    enabled=self._is_plugin_enabled(plugin_id),
                    user_present=user_present,
                    user_version=user_version,
                    transaction=transaction_status,
                    can_uninstall=(
                        self.installer is not None
                        and user_present
                        and not transaction_blocks_changes
                        and uninstall_dependency_safe
                    ),
                    can_rollback=(
                        rollback_candidate is not None and not blocking_dependents
                    ),
                    restart_required=(
                        transaction_status.requires_restart
                        if transaction_status
                        else False
                    ),
                    update_error=update_error,
                    compatibility_error=compatibility_error,
                    loaded=plugin_id in self.runtime._loaded_plugins,
                    blocked_code=blocked_reason.code if blocked_reason else None,
                    blocked_reason=blocked_reason.message if blocked_reason else None,
                    blocking_dependents=blocking_dependents,
                )
            )
        return tuple(statuses)

    def get_plugin_status(self, plugin_id: str) -> PluginStatus | None:
        return next(
            (
                status
                for status in self.get_plugin_statuses()
                if status.plugin_id == plugin_id
            ),
            None,
        )

    def get_plugin(self, plugin_id: str):
        """Returns the loaded plugin instance or None."""
        return self.runtime.get_plugin(plugin_id)

    def get_load_errors(self) -> dict:
        """Returns any errors that occurred during plugin loading."""
        errors = dict(self.runtime.load_errors)
        errors.update(
            {
                f"plugin-update:{plugin_id}": details["message"]
                for plugin_id, details in self._update_errors.items()
            }
        )
        return errors

    def record_load_error(self, plugin_id: str, error: str):
        """Manually record a load error for a plugin."""
        self.runtime.load_errors[plugin_id] = error

    def install_plugin(self, file_path: str) -> tuple[bool, str]:
        """Validate and queue one package without blocking other plugin IDs."""
        if self.installer is None:
            return False, self._installer_unavailable_message()
        if not os.path.exists(file_path):
            return False, f"File not found: {file_path}"

        ext = Path(file_path).suffix.lower()
        if ext == ".pyd":
            return (
                False,
                "Standalone .pyd files are not plugins. Package the native module "
                "inside a validated .atplugin archive.",
            )
        if ext not in {".atplugin", ".zip"}:
            return False, "Unsupported plugin package. Use .atplugin or legacy .zip."

        allow_legacy_zip = ext == ".zip"
        try:
            transaction = self.installer.import_package(
                file_path,
                allow_legacy_zip=allow_legacy_zip,
                manifest_validator=lambda manifest: self._preflight_plugin_change(
                    manifest.plugin_id,
                    manifest,
                ),
            )
            return (
                True,
                f"Plugin {transaction.plugin_id} {transaction.version} is queued. "
                "Restart Agile Tiles once after importing all packages.",
            )
        except PluginInstallerError as exc:
            logger.error("Failed to queue plugin package: %s", exc, exc_info=True)
            return False, f"Plugin package error [{exc.code}]: {exc}"

    def prepare_pending_updates(self):
        """Recover and apply queued transactions before plugin discovery."""
        if self._pending_updates_prepared:
            return list(self._update_results)

        self._pending_updates_prepared = True
        if self.installer is None:
            error = self._installer_error or PluginInstallerError(
                "INSTALLER_UNAVAILABLE", "Plugin installer is unavailable."
            )
            raise PluginInstallerError(error.code, str(error))

        with self.installer.transaction_session():
            results = self._recover_and_apply_pending_locked()
            self._update_results = results
            self._collect_unverified_updates()
        return list(results)

    def _recover_and_apply_pending_locked(self):
        transactions = sorted(
            self.installer.recover_transactions(),
            key=lambda item: (item.created_at_ns, item.transaction_id),
        )
        results = []
        for transaction in transactions:
            if transaction.state == "failed":
                self._blocked_user_plugins.add(transaction.plugin_id)
                self._record_update_error(
                    transaction.plugin_id,
                    transaction,
                    transaction.error_message or "Plugin transaction requires recovery.",
                    rollback="failed",
                )
                continue
            if transaction.state == "rollback_pending":
                try:
                    rolled_back = self.installer.rollback(transaction.transaction_id)
                    results.append(rolled_back)
                    logger.info(
                        "Applied pending rollback for plugin %s transaction %s.",
                        rolled_back.plugin_id,
                        rolled_back.transaction_id,
                    )
                except PluginInstallerError as exc:
                    current = self.installer.get_transaction(
                        transaction.transaction_id
                    )
                    results.append(current)
                    self._blocked_user_plugins.add(transaction.plugin_id)
                    self._record_update_error(
                        transaction.plugin_id,
                        current,
                        str(exc),
                        rollback="failed",
                    )
                    logger.error(
                        "Failed to apply pending plugin rollback %s: %s",
                        transaction.transaction_id,
                        exc,
                        exc_info=True,
                    )
                continue
            if transaction.state != "pending":
                continue
            try:
                applied = self.installer.apply_pending(
                    transaction.transaction_id,
                    manifest_validator=self._preflight_pending_plugin_change,
                )
                results.append(applied)
                logger.info(
                    "Applied pending plugin %s transaction %s.",
                    applied.plugin_id,
                    applied.transaction_id,
                )
            except PluginInstallerError as exc:
                logger.error(
                    "Failed to apply pending plugin transaction %s: %s",
                    transaction.transaction_id,
                    exc,
                    exc_info=True,
                )
                current = self.installer.get_transaction(transaction.transaction_id)
                results.append(current)
                if current.state == "failed":
                    self._blocked_user_plugins.add(current.plugin_id)
                    self._record_update_error(
                        current.plugin_id,
                        current,
                        current.error_message or str(exc),
                        rollback="failed",
                    )
        return results

    def _preflight_pending_plugin_change(self, transaction, manifest):
        """Recheck graph constraints immediately before a queued swap occurs."""
        replacement = (
            manifest
            if transaction.operation == "install"
            else self._uninstall_replacement_manifest(transaction.plugin_id)
        )
        self._preflight_plugin_change(
            transaction.plugin_id, replacement, check_target=False
        )

    def queue_uninstall_plugin(self, plugin_id: str) -> tuple[bool, str]:
        """Queue removal without blocking changes for other plugin IDs."""
        if self.installer is None:
            return False, self._installer_unavailable_message()
        user_present, _ = self._get_user_plugin_state(plugin_id)
        if not user_present:
            return False, "No user-installed plugin version is available to uninstall."
        try:
            self._preflight_plugin_change(
                plugin_id,
                self._uninstall_replacement_manifest(plugin_id),
                check_target=False,
            )
            transaction = self.installer.stage_uninstall(plugin_id)
            return (
                True,
                f"Plugin {transaction.plugin_id} removal is queued. "
                "Restart once after queuing all changes.",
            )
        except PluginInstallerError as exc:
            return False, f"Plugin uninstall error [{exc.code}]: {exc}"

    def queue_rollback_plugin(self, plugin_id: str) -> tuple[bool, str]:
        """Queue the newest rollbackable install transaction for restart."""
        if self.installer is None:
            return False, self._installer_unavailable_message()
        try:
            self._ensure_no_pending_plugin_change()
            candidate = self._find_rollback_candidate(
                self.installer.list_transactions(plugin_id=plugin_id)
            )
            if candidate is None:
                return False, "No rollbackable plugin update is available."
            dependents = self._blocking_dependents(plugin_id)
            if dependents:
                raise PluginInstallerError(
                    "PLUGIN_DEPENDENTS_BLOCKED",
                    "Reinstall the target version to validate enabled dependents: "
                    + ", ".join(dependents),
                )
            requested = self.installer.request_rollback(candidate.transaction_id)
            self._replace_update_result(requested)
            return (
                True,
                f"Plugin {plugin_id} rollback is queued. Restart to apply it.",
            )
        except PluginInstallerError as exc:
            return False, f"Plugin rollback error [{exc.code}]: {exc}"

    def cancel_pending_plugin_change(self, plugin_id: str) -> tuple[bool, str]:
        """Cancel the current not-yet-applied plugin transaction."""
        if self.installer is None:
            return False, self._installer_unavailable_message()
        try:
            pending = next(
                (
                    transaction
                    for transaction in self.installer.list_transactions(
                        plugin_id=plugin_id,
                        states={"pending"},
                    )
                ),
                None,
            )
            if pending is None:
                return False, "No pending plugin change is available to cancel."
            cancelled = self.installer.rollback(pending.transaction_id)
            self._replace_update_result(cancelled)
            return True, f"Pending change for plugin {plugin_id} was cancelled."
        except PluginInstallerError as exc:
            return False, f"Plugin cancellation error [{exc.code}]: {exc}"

    def _installer_unavailable_message(self) -> str:
        error = self._installer_error
        if error is None:
            return "Plugin installer is unavailable."
        return f"Plugin installer unavailable [{error.code}]: {error}"

    def _get_user_plugin_state(self, plugin_id: str) -> tuple[bool, str | None]:
        user_root = Path(self.user_plugins_dir)
        plugin_dir = user_root / plugin_id
        if plugin_dir.parent != user_root or plugin_dir.name != plugin_id:
            return False, None
        try:
            user_present = plugin_dir.exists()
        except OSError:
            user_present = True
        if not user_present:
            return False, None

        loaded = ManifestLoader.load_with_model(
            str(plugin_dir),
            log_errors=False,
        )
        if loaded is None or loaded[0].get("id") != plugin_id:
            return True, None
        return True, loaded[0].get("version")

    def _get_user_plugin_ids(self) -> set[str]:
        user_root = Path(self.user_plugins_dir)
        try:
            entries = tuple(user_root.iterdir())
        except FileNotFoundError:
            return set()
        except OSError as error:
            logger.warning(
                "Cannot enumerate user plugins for management status: %s",
                error,
            )
            return set()

        plugin_ids = set()
        for entry in entries:
            if not is_safe_plugin_id(entry.name):
                continue
            try:
                if entry.is_dir():
                    plugin_ids.add(entry.name)
            except OSError:
                continue
        return plugin_ids

    @staticmethod
    def _find_rollback_candidate(transactions):
        for transaction in transactions:
            if transaction.state == "rolled_back":
                continue
            if transaction.state != "applied":
                return None
            if transaction.operation == "install":
                return transaction
            return None
        return None

    def _collect_unverified_updates(self):
        self._unverified_updates = {}
        seen_plugins = set()
        transactions = self.installer.list_transactions(states={"applied"})
        for transaction in transactions:
            if transaction.plugin_id in seen_plugins:
                continue
            seen_plugins.add(transaction.plugin_id)
            if transaction.operation == "install" and transaction.load_verified is False:
                self._unverified_updates[transaction.plugin_id] = transaction

    def _matching_unverified_update(self, plugin_id: str, item_path: str):
        transaction = self._unverified_updates.get(plugin_id)
        source = self._plugin_sources.get(plugin_id)
        if transaction is None or not source or source.get("kind") != "user":
            return None
        expected_path = self._normalize_path(
            str(Path(self.user_plugins_dir) / plugin_id)
        )
        if os.path.normcase(self._normalize_path(item_path)) != os.path.normcase(
            expected_path
        ):
            return None
        return transaction

    def _mark_update_load_verified(self, plugin_id: str, item_path: str):
        transaction = self._matching_unverified_update(plugin_id, item_path)
        if transaction is None or self.installer is None:
            return
        try:
            verified = self.installer.mark_load_verified(transaction.transaction_id)
            self._replace_update_result(verified)
            self._unverified_updates.pop(plugin_id, None)
        except PluginInstallerError as exc:
            self._record_update_error(
                plugin_id,
                transaction,
                f"Plugin loaded, but update verification could not be saved: {exc}",
                rollback="not-required",
            )

    def _recover_failed_update(self, plugin_id: str, item_path: str) -> bool:
        transaction = self._matching_unverified_update(plugin_id, item_path)
        if transaction is None or self.installer is None:
            return False

        load_error = self.runtime.load_errors.get(plugin_id, "Plugin failed to load.")
        if self._contains_native_binary(item_path):
            try:
                requested = self.installer.request_rollback(
                    transaction.transaction_id
                )
                self._replace_update_result(requested)
                self._unverified_updates.pop(plugin_id, None)
                self._restart_required_plugins.add(plugin_id)
                self._record_update_error(
                    plugin_id,
                    requested,
                    f"{load_error} Rollback is queued for the next restart.",
                    rollback="pending",
                )
            except PluginInstallerError as exc:
                self._blocked_user_plugins.add(plugin_id)
                self._record_update_error(
                    plugin_id,
                    transaction,
                    f"{load_error} Rollback could not be queued: {exc}",
                    rollback="failed",
                )
            return False

        try:
            rolled_back = self.installer.rollback(transaction.transaction_id)
            self._replace_update_result(rolled_back)
            self._unverified_updates.pop(plugin_id, None)
            self._record_update_error(
                plugin_id,
                rolled_back,
                f"{load_error} The update was rolled back automatically.",
                rollback="completed",
            )
            self.discover_plugins()
            return plugin_id in self._manifests
        except PluginInstallerError as exc:
            self._blocked_user_plugins.add(plugin_id)
            current = self.installer.get_transaction(transaction.transaction_id)
            self._record_update_error(
                plugin_id,
                current,
                f"{load_error} Automatic rollback failed: {exc}",
                rollback="failed",
            )
            self.discover_plugins()
            return plugin_id in self._manifests

    def _request_incompatible_update_rollbacks(self, compatibility_errors: dict):
        if self.installer is None:
            return
        for plugin_id, details in compatibility_errors.items():
            transaction = self._unverified_updates.get(plugin_id)
            if transaction is None:
                continue
            try:
                requested = self.installer.request_rollback(
                    transaction.transaction_id
                )
                self._replace_update_result(requested)
                self._unverified_updates.pop(plugin_id, None)
                self._record_update_error(
                    plugin_id,
                    requested,
                    (
                        f"Plugin update is incompatible [{details['code']}]: "
                        f"{details['message']}. Rollback is queued for restart."
                    ),
                    rollback="pending",
                )
            except PluginInstallerError as exc:
                self._blocked_user_plugins.add(plugin_id)
                self._record_update_error(
                    plugin_id,
                    transaction,
                    f"Incompatible update rollback could not be queued: {exc}",
                    rollback="failed",
                )

    @staticmethod
    def _contains_native_binary(plugin_path: str) -> bool:
        try:
            return any(
                path.is_file() and path.suffix.lower() in {".pyd", ".dll"}
                for path in Path(plugin_path).rglob("*")
            )
        except OSError:
            return True

    def _replace_update_result(self, replacement):
        replaced = False
        updated = []
        for transaction in self._update_results:
            if transaction.transaction_id == replacement.transaction_id:
                updated.append(replacement)
                replaced = True
            else:
                updated.append(transaction)
        if not replaced:
            updated.append(replacement)
        self._update_results = updated

    def _record_update_error(
        self,
        plugin_id: str,
        transaction,
        message: str,
        *,
        rollback: str,
    ):
        self._update_errors[plugin_id] = {
            "code": transaction.error_code or "UPDATE_LOAD_FAILED",
            "message": message,
            "transaction_id": transaction.transaction_id,
            "rollback": rollback,
        }

    def shutdown(self):
        """Shutdown all loaded plugins."""
        for plugin_id in reversed(tuple(self.runtime._loaded_plugins)):
            self.runtime.unload_plugin(plugin_id)
        logger.info("PluginManager shutdown complete.")
