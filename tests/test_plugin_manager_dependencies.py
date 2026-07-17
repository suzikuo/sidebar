import tempfile
import unittest
from pathlib import Path

from core.plugin_system.event_bus import EventBus
from core.plugin_system.plugin_manager import PluginManager
from core.plugin_system.plugin_manifest import HostEnvironment, parse_manifest
from core.plugin_system.plugin_installer import PluginInstallerError


def _manifest(plugin_id, plugins=None, version="1.0.0"):
    data = {
        "manifest_version": 2,
        "id": plugin_id,
        "name": plugin_id,
        "version": version,
        "entry": "plugin.py",
        "class": "Plugin",
        "api_version": "1.0",
        "compatibility": {
            "app": ">=1.0",
            "python_abi": "cp311",
            "platform": "win_amd64",
        },
        "dependencies": {
            "host": [],
            "python": [],
            "plugins": plugins or {},
        },
        "files": {"plugin.py": "0" * 64},
        "native_modules": [],
        "requires_restart": False,
        "ui": {"type": "native"},
    }
    return data, parse_manifest(data)


class _StateStore:
    def __init__(self, order):
        self.data = {
            "settings": {
                "plugins": {
                    "order": list(order),
                    "disabled": [],
                }
            }
        }

    def get(self, key, default=None):
        return self.data.get(key, default)

    def save(self):
        pass

    def set_disabled(self, plugin_ids):
        self.data["settings"]["plugins"]["disabled"] = list(plugin_ids)


class _PluginInstance:
    def __init__(self, plugin_id):
        self.plugin_id = plugin_id


class _RecordingRuntime:
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self._loaded_plugins = {}
        self.load_errors = {}
        self.events = []

    def load_plugin(self, manifest, plugin_dir):
        plugin_id = manifest["id"]
        self.events.append(("load", plugin_id))
        if plugin_id in self.fail_ids:
            self.load_errors[plugin_id] = "on_load failed"
            return False
        self._loaded_plugins[plugin_id] = _PluginInstance(plugin_id)
        return True

    def unload_plugin(self, plugin_id):
        self.events.append(("unload", plugin_id))
        self._loaded_plugins.pop(plugin_id, None)

    def get_plugin(self, plugin_id):
        return self._loaded_plugins.get(plugin_id)


class PluginManagerDependenciesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.managers = []

    def tearDown(self):
        for manager in self.managers:
            manager.shutdown()
        self.temp_dir.cleanup()

    def _manager(self, manifests, *, order, fail_ids=()):
        state_store = _StateStore(order)
        manager = PluginManager(
            [str(self.root / "bundled")],
            EventBus(),
            state_store=state_store,
            user_plugins_dir=str(self.root / "user"),
            transaction_root=str(self.root / "transactions"),
            host_environment=HostEnvironment(
                app_version="1.0.0",
                api_version="1.0",
                python_abi="cp311",
                platform_tag="win_amd64",
                host_packages={},
            ),
        )
        manager._pending_updates_prepared = True
        manager._manifests = {
            plugin_id: raw for plugin_id, (raw, model) in manifests.items()
        }
        manager._manifest_models = {
            plugin_id: model for plugin_id, (raw, model) in manifests.items()
        }
        manager._plugin_paths = {
            plugin_id: str(self.root / plugin_id) for plugin_id in manifests
        }
        manager.discover_plugins = lambda: manager.get_all_manifests()
        runtime = _RecordingRuntime(fail_ids)
        manager.runtime = runtime
        self.managers.append(manager)
        return manager, runtime, state_store

    def test_provider_loads_before_consumer_without_changing_ui_order(self):
        manager, runtime, state_store = self._manager(
            {
                "consumer": _manifest("consumer", {"provider": ">=1"}),
                "provider": _manifest("provider"),
            },
            order=("consumer", "provider"),
        )

        manager.discover_and_load()

        self.assertEqual(
            runtime.events,
            [("load", "provider"), ("load", "consumer")],
        )
        self.assertEqual(manager.get_plugin_order(), ["consumer", "provider"])
        self.assertEqual(
            state_store.data["settings"]["plugins"]["order"],
            ["consumer", "provider"],
        )

    def test_missing_and_cycle_plugins_are_blocked_but_independent_loads(self):
        manager, runtime, _ = self._manager(
            {
                "missing-consumer": _manifest(
                    "missing-consumer", {"not-installed": ">=1"}
                ),
                "cycle-a": _manifest("cycle-a", {"cycle-b": ">=1"}),
                "cycle-b": _manifest("cycle-b", {"cycle-a": ">=1"}),
                "independent": _manifest("independent"),
            },
            order=("missing-consumer", "cycle-a", "cycle-b", "independent"),
        )

        manager.discover_and_load()

        self.assertEqual(runtime.events, [("load", "independent")])
        errors = manager.get_dependency_errors()
        self.assertEqual(
            errors["missing-consumer"][0].code,
            "PLUGIN_DEPENDENCY_MISSING",
        )
        self.assertEqual(errors["cycle-a"][0].code, "PLUGIN_DEPENDENCY_CYCLE")
        self.assertEqual(errors["cycle-b"][0].code, "PLUGIN_DEPENDENCY_CYCLE")

    def test_provider_load_failure_blocks_all_consumers_before_instantiation(self):
        manager, runtime, _ = self._manager(
            {
                "provider": _manifest("provider"),
                "consumer": _manifest("consumer", {"provider": ">=1"}),
                "transitive": _manifest("transitive", {"consumer": ">=1"}),
                "independent": _manifest("independent"),
            },
            order=("provider", "consumer", "transitive", "independent"),
            fail_ids={"provider"},
        )

        manager.discover_and_load()

        self.assertEqual(
            runtime.events,
            [("load", "provider"), ("load", "independent")],
        )
        self.assertIsNone(manager.get_plugin("consumer"))
        self.assertIsNone(manager.get_plugin("transitive"))
        errors = manager.get_dependency_errors()
        self.assertEqual(
            errors["consumer"][0].code,
            "PLUGIN_DEPENDENCY_LOAD_FAILED",
        )
        self.assertEqual(errors["consumer"][0].dependency_id, "provider")
        self.assertEqual(errors["transitive"][0].dependency_id, "provider")

    def test_direct_load_requires_provider_to_be_actually_loaded(self):
        manager, runtime, _ = self._manager(
            {
                "consumer": _manifest("consumer", {"provider": ">=1"}),
                "provider": _manifest("provider"),
            },
            order=("consumer", "provider"),
        )
        manager._plugin_graph = manager._resolve_enabled_plugin_graph()

        self.assertFalse(manager._load_single_plugin("consumer"))
        self.assertEqual(runtime.events, [])
        self.assertEqual(
            manager.get_dependency_errors()["consumer"][0].dependency_id,
            "provider",
        )

        self.assertTrue(manager._load_single_plugin("provider"))
        self.assertTrue(manager._load_single_plugin("consumer"))
        self.assertNotIn("consumer", manager.get_dependency_errors())

    def test_refresh_unloads_reverse_and_loads_forward_graph_order(self):
        manager, runtime, state_store = self._manager(
            {
                "provider": _manifest("provider"),
                "consumer": _manifest("consumer", {"provider": ">=1"}),
                "independent": _manifest("independent"),
            },
            order=("provider", "consumer", "independent"),
        )
        manager.discover_and_load()
        runtime.events.clear()

        state_store.set_disabled({"provider"})
        manager.refresh_plugin_state()

        self.assertEqual(
            runtime.events,
            [("unload", "consumer"), ("unload", "provider")],
        )
        self.assertEqual(tuple(runtime._loaded_plugins), ("independent",))

        runtime.events.clear()
        state_store.set_disabled(set())
        manager.refresh_plugin_state()

        self.assertEqual(
            runtime.events,
            [("load", "provider"), ("load", "consumer")],
        )

    def test_disabling_provider_is_rejected_without_implicit_cascade(self):
        manager, runtime, state_store = self._manager(
            {
                "provider": _manifest("provider"),
                "consumer": _manifest("consumer", {"provider": ">=1"}),
            },
            order=("provider", "consumer"),
        )
        manager.discover_and_load()
        runtime.events.clear()

        success, message = manager.set_plugin_enabled("provider", False)

        self.assertFalse(success)
        self.assertIn("PLUGIN_DEPENDENTS_BLOCKED", message)
        self.assertEqual(state_store.data["settings"]["plugins"]["disabled"], [])
        self.assertEqual(runtime.events, [])
        self.assertTrue(manager.get_plugin_status("provider").loaded)
        self.assertEqual(
            manager.get_plugin_status("provider").blocking_dependents,
            ("consumer",),
        )

    def test_enabling_consumer_requires_its_provider_to_be_enabled(self):
        manager, runtime, state_store = self._manager(
            {
                "provider": _manifest("provider"),
                "consumer": _manifest("consumer", {"provider": ">=1"}),
            },
            order=("provider", "consumer"),
        )
        state_store.set_disabled({"provider", "consumer"})
        manager._plugin_graph = manager._resolve_enabled_plugin_graph()

        success, message = manager.set_plugin_enabled("consumer", True)

        self.assertFalse(success)
        self.assertIn("PLUGIN_DEPENDENCY_DISABLED", message)
        self.assertEqual(
            set(state_store.data["settings"]["plugins"]["disabled"]),
            {"consumer", "provider"},
        )
        self.assertEqual(runtime.events, [])
        status = manager.get_plugin_status("consumer")
        self.assertFalse(status.loaded)
        self.assertTrue(status.enabled is False)

    def test_provider_update_cannot_break_enabled_consumer_version_range(self):
        manager, _, _ = self._manager(
            {
                "provider": _manifest("provider", version="2.0.0"),
                "consumer": _manifest("consumer", {"provider": ">=2"}),
            },
            order=("provider", "consumer"),
        )
        manager._plugin_graph = manager._resolve_enabled_plugin_graph()
        replacement = _manifest("provider", version="1.0.0")[1]

        with self.assertRaises(PluginInstallerError) as caught:
            manager._preflight_plugin_change("provider", replacement)

        self.assertEqual(caught.exception.code, "PLUGIN_DEPENDENTS_BLOCKED")

    def test_shutdown_unloads_consumer_before_provider(self):
        manager, runtime, _ = self._manager(
            {
                "consumer": _manifest("consumer", {"provider": ">=1"}),
                "provider": _manifest("provider"),
            },
            order=("consumer", "provider"),
        )
        manager.discover_and_load()
        runtime.events.clear()

        manager.shutdown()

        self.assertEqual(
            runtime.events,
            [("unload", "consumer"), ("unload", "provider")],
        )


if __name__ == "__main__":
    unittest.main()
