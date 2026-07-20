"""Capability-scoped API exposed only to the local control center page."""

from pathlib import Path

from core.api_gateway import ApiError


class ControlCenterApiService:
    READ_CAPABILITY = "core.control_center.read"
    MANAGE_CAPABILITY = "core.control_center.manage"

    def __init__(
        self,
        registry,
        settings_manager,
        plugin_manager,
        catalog_service,
        *,
        version_path,
        choose_plugin_package,
        restart_application,
        open_data_directory,
    ):
        self._registry = registry
        self._settings_manager = settings_manager
        self._plugin_manager = plugin_manager
        self._catalog = catalog_service
        self._version_path = Path(version_path)
        self._choose_plugin_package = choose_plugin_package
        self._restart_application = restart_application
        self._open_data_directory = open_data_directory
        self._event_publisher = None

    def set_event_publisher(self, publisher):
        self._event_publisher = publisher

    def register_routes(self):
        read = self.READ_CAPABILITY
        manage = self.MANAGE_CAPABILITY
        routes = [
            ("core/control-center/overview", self._overview, read),
            ("core/control-center/plugins", self._plugins, read),
            ("core/control-center/catalog", self._catalog_snapshot, read),
            ("core/control-center/plugin-enable", self._set_plugin_enabled, manage),
            ("core/control-center/plugin-order", self._set_plugin_order, manage),
            ("core/control-center/plugin-import", self._import_plugin, manage),
            ("core/control-center/catalog-install", self._install_catalog_plugin, manage),
            ("core/control-center/plugin-uninstall", self._uninstall_plugin, manage),
            ("core/control-center/plugin-rollback", self._rollback_plugin, manage),
            ("core/control-center/plugin-cancel", self._cancel_plugin_change, manage),
            ("core/control-center/open-data", self._open_data, manage),
            ("core/control-center/restart", self._restart, manage),
        ]
        return [
            self._registry.register_route(
                "core", route, handler, exported_capability=capability
            )
            for route, handler, capability in routes
        ]

    def _overview(self, payload, context):
        del payload, context
        statuses = self._plugin_manager.get_plugin_statuses()
        installed = [status for status in statuses if status.selected_version]
        errors = self._plugin_manager.get_load_errors()
        return {
            "version": self._read_version(),
            "pluginCount": len(installed),
            "enabledPluginCount": sum(status.enabled for status in installed),
            "loadedPluginCount": sum(status.loaded for status in installed),
            "pendingRestartCount": sum(status.restart_required for status in statuses),
            "errorCount": len(errors),
            "errors": [
                {"source": source, "message": str(message)}
                for source, message in sorted(errors.items())[:20]
            ],
        }

    def _plugins(self, payload, context):
        del payload, context
        return {
            "order": self._plugin_manager.get_plugin_order(),
            "plugins": [
                self._serialize_plugin_status(status)
                for status in self._plugin_manager.get_plugin_statuses()
            ],
        }

    def _catalog_snapshot(self, payload, context):
        del payload, context
        return self._catalog.snapshot()

    def _set_plugin_enabled(self, payload, context):
        del context
        plugin_id = self._plugin_id(payload)
        enabled = payload.get("enabled")
        if type(enabled) is not bool:
            raise ApiError("INVALID_REQUEST", "Plugin enabled state must be a boolean.")
        result = self._run_plugin_action(
            self._plugin_manager.set_plugin_enabled, plugin_id, enabled
        )
        self._publish_plugins_changed()
        return result

    def _set_plugin_order(self, payload, context):
        del context
        order = payload.get("order")
        if not isinstance(order, list) or any(
            not isinstance(plugin_id, str) for plugin_id in order
        ):
            raise ApiError("INVALID_REQUEST", "Plugin order must be a list of IDs.")
        if len(order) != len(set(order)):
            raise ApiError("INVALID_REQUEST", "Plugin order contains duplicate IDs.")
        current = self._plugin_manager.get_plugin_order()
        if set(order) != set(current):
            raise ApiError("INVALID_REQUEST", "Plugin order must include every installed plugin.")
        self._plugin_manager.set_plugin_order(list(order))
        self._publish_plugins_changed()
        return {"order": list(order)}

    def _import_plugin(self, payload, context):
        del payload, context
        package_path = self._choose_plugin_package()
        if not package_path:
            return {"cancelled": True}
        result = self._run_plugin_action(
            self._plugin_manager.install_plugin, package_path
        )
        self._publish_plugins_changed()
        return {**result, "cancelled": False}

    def _install_catalog_plugin(self, payload, context):
        del context
        plugin_id = self._plugin_id(payload)
        package_path = self._catalog.package_path(plugin_id)
        if package_path is None:
            raise ApiError(
                "CATALOG_PACKAGE_UNAVAILABLE",
                "The requested official plugin package is unavailable or incompatible.",
            )
        result = self._run_plugin_action(
            self._plugin_manager.install_plugin, str(package_path)
        )
        self._publish_plugins_changed()
        return result

    def _uninstall_plugin(self, payload, context):
        del context
        result = self._run_plugin_action(
            self._plugin_manager.queue_uninstall_plugin,
            self._plugin_id(payload),
        )
        self._publish_plugins_changed()
        return result

    def _rollback_plugin(self, payload, context):
        del context
        result = self._run_plugin_action(
            self._plugin_manager.queue_rollback_plugin,
            self._plugin_id(payload),
        )
        self._publish_plugins_changed()
        return result

    def _cancel_plugin_change(self, payload, context):
        del context
        result = self._run_plugin_action(
            self._plugin_manager.cancel_pending_plugin_change,
            self._plugin_id(payload),
        )
        self._publish_plugins_changed()
        return result

    def _open_data(self, payload, context):
        del payload, context
        if not self._open_data_directory():
            raise ApiError("OPEN_FAILED", "The application data directory could not be opened.")
        return {"opened": True}

    def _restart(self, payload, context):
        del payload, context
        from PySide6.QtCore import QTimer

        QTimer.singleShot(250, self._restart_application)
        return {"scheduled": True}

    def _publish_plugins_changed(self):
        if self._event_publisher:
            self._event_publisher("plugins.changed", {})

    @staticmethod
    def _plugin_id(payload):
        plugin_id = payload.get("pluginId")
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise ApiError("INVALID_REQUEST", "Plugin ID is required.")
        return plugin_id.strip()

    @staticmethod
    def _run_plugin_action(action, *args):
        success, message = action(*args)
        if not success:
            raise ApiError("PLUGIN_ACTION_FAILED", message)
        return {"message": message}

    @staticmethod
    def _serialize_plugin_status(status):
        transaction = status.transaction
        return {
            "pluginId": status.plugin_id,
            "name": status.name,
            "selectedVersion": status.selected_version,
            "source": status.source,
            "enabled": status.enabled,
            "userPresent": status.user_present,
            "userVersion": status.user_version,
            "loaded": status.loaded,
            "canUninstall": status.can_uninstall,
            "canRollback": status.can_rollback,
            "restartRequired": status.restart_required,
            "updateError": status.update_error,
            "compatibilityError": status.compatibility_error,
            "blockedCode": status.blocked_code,
            "blockedReason": status.blocked_reason,
            "blockingDependents": list(status.blocking_dependents),
            "transaction": (
                {
                    "operation": transaction.operation,
                    "state": transaction.state,
                    "version": transaction.version,
                    "generation": transaction.generation,
                    "loadVerified": transaction.load_verified,
                    "errorCode": transaction.error_code,
                    "errorMessage": transaction.error_message,
                    "requiresRestart": transaction.requires_restart,
                }
                if transaction
                else None
            ),
        }

    def _read_version(self):
        try:
            return self._version_path.read_text(encoding="utf-8").strip() or "unknown"
        except OSError:
            return "unknown"
