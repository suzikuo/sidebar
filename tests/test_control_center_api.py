import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.api_gateway import ApiCaller, ApiRegistry
from core.control_center.api import ControlCenterApiService
def _status(plugin_id="sample", **changes):
    values = dict(
        plugin_id=plugin_id,
        name="Sample",
        selected_version="1.0.0",
        source="user",
        enabled=True,
        user_present=True,
        user_version="1.0.0",
        transaction=None,
        can_uninstall=True,
        can_rollback=False,
        restart_required=False,
        loaded=True,
        update_error=None,
        compatibility_error=None,
        blocked_code=None,
        blocked_reason=None,
        blocking_dependents=(),
    )
    values.update(changes)
    return SimpleNamespace(**values)


def _replace_status(status, **changes):
    values = vars(status).copy()
    values.update(changes)
    return SimpleNamespace(**values)


class _PluginManager:
    def __init__(self):
        self.statuses = [_status()]
        self.order = ["sample"]
        self.calls = []

    def get_plugin_statuses(self):
        return tuple(self.statuses)

    def get_plugin_order(self):
        return list(self.order)

    def get_load_errors(self):
        return {"sample": "load failed"}

    def set_plugin_enabled(self, plugin_id, enabled):
        self.calls.append(("enable", plugin_id, enabled))
        self.statuses = [
            _replace_status(self.statuses[0], enabled=enabled, loaded=enabled)
        ]
        return True, "updated"

    def set_plugin_order(self, order):
        self.calls.append(("order", list(order)))
        self.order = list(order)

    def install_plugin(self, path):
        self.calls.append(("install", path))
        return True, "queued"

    def queue_uninstall_plugin(self, plugin_id):
        self.calls.append(("uninstall", plugin_id))
        return True, "queued"

    def queue_rollback_plugin(self, plugin_id):
        self.calls.append(("rollback", plugin_id))
        return True, "queued"

    def cancel_pending_plugin_change(self, plugin_id):
        self.calls.append(("cancel", plugin_id))
        return True, "cancelled"


class _Catalog:
    def __init__(self, package_path):
        self._package_path = package_path

    def snapshot(self):
        return {"entries": [{"pluginId": "sample"}], "errors": []}

    def package_path(self, plugin_id):
        return self._package_path if plugin_id == "sample" else None


class ControlCenterApiServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        version_path = Path(self.temp_dir.name) / "VERSION"
        version_path.write_text("1.2.3\n", encoding="utf-8")
        package_path = Path(self.temp_dir.name) / "sample.atplugin"
        package_path.write_bytes(b"package")
        self.registry = ApiRegistry()
        self.manager = _PluginManager()
        self.picked = str(package_path)
        self.opened = False
        self.events = []
        self.service = ControlCenterApiService(
            self.registry,
            object(),
            self.manager,
            _Catalog(package_path),
            version_path=version_path,
            choose_plugin_package=lambda: self.picked,
            restart_application=lambda: None,
            open_data_directory=self._open_data,
        )
        self.service.set_event_publisher(
            lambda event, payload: self.events.append((event, payload))
        )
        self.service.register_routes()
        self.reader = ApiCaller.web(
            "control-center", {ControlCenterApiService.READ_CAPABILITY}
        )
        self.manager_caller = ApiCaller.web(
            "control-center",
            {
                ControlCenterApiService.READ_CAPABILITY,
                ControlCenterApiService.MANAGE_CAPABILITY,
            },
        )

    def _open_data(self):
        self.opened = True
        return True

    def test_overview_and_plugin_snapshot_are_capability_scoped(self):
        denied = self.registry.invoke(
            ApiCaller.web("control-center"),
            "core/control-center/overview",
            {},
        )
        overview = self.registry.call(
            self.reader,
            "core/control-center/overview",
            {},
        )
        plugins = self.registry.call(
            self.reader,
            "core/control-center/plugins",
            {},
        )

        self.assertEqual(denied["code"], "FORBIDDEN")
        self.assertEqual(overview["version"], "1.2.3")
        self.assertEqual(overview["pluginCount"], 1)
        self.assertEqual(overview["errorCount"], 1)
        self.assertEqual(plugins["plugins"][0]["pluginId"], "sample")
        self.assertNotIn("packagePath", plugins["plugins"][0])

    def test_management_routes_use_public_plugin_manager_actions(self):
        route = "core/control-center/plugin-enable"
        denied = self.registry.invoke(
            self.reader,
            route,
            {"pluginId": "sample", "enabled": False},
        )
        enabled = self.registry.invoke(
            self.manager_caller,
            route,
            {"pluginId": "sample", "enabled": False},
        )
        installed = self.registry.invoke(
            self.manager_caller,
            "core/control-center/catalog-install",
            {"pluginId": "sample"},
        )

        self.assertEqual(denied["code"], "FORBIDDEN")
        self.assertTrue(enabled["ok"])
        self.assertTrue(installed["ok"])
        self.assertIn(("enable", "sample", False), self.manager.calls)
        self.assertTrue(any(call[0] == "install" for call in self.manager.calls))
        self.assertEqual(self.events[-1], ("plugins.changed", {}))

    def test_import_cancellation_and_open_data_do_not_expose_paths(self):
        self.picked = ""
        imported = self.registry.call(
            self.manager_caller,
            "core/control-center/plugin-import",
            {},
        )
        opened = self.registry.call(
            self.manager_caller,
            "core/control-center/open-data",
            {},
        )

        self.assertEqual(imported, {"cancelled": True})
        self.assertEqual(opened, {"opened": True})
        self.assertTrue(self.opened)

    def test_transaction_status_is_serialized_without_dataclass_objects(self):
        transaction = SimpleNamespace(
            operation="install",
            state="pending",
            version="2.0.0",
            generation=2,
            load_verified=None,
            error_code=None,
            error_message=None,
            requires_restart=True,
        )
        self.manager.statuses = [
            _status(transaction=transaction, restart_required=True)
        ]

        result = self.registry.call(
            self.reader,
            "core/control-center/plugins",
            {},
        )
        serialized = result["plugins"][0]["transaction"]
        self.assertEqual(serialized["state"], "pending")
        self.assertTrue(serialized["requiresRestart"])


if __name__ == "__main__":
    unittest.main()
