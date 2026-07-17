import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.api_gateway import ApiCaller, ApiRegistry
from core.plugin_system.event_bus import EventBus
from core.plugin_system.plugin_context import PluginContext
from core.plugin_system.plugin_runtime import PluginRuntime
from core.plugin_system.scheduler import PluginScheduler


class EventBusLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_token_owner_and_legacy_unsubscribe_are_supported(self):
        event_bus = EventBus()
        calls = []

        first_token = event_bus.subscribe(
            "status.changed",
            lambda data: calls.append(("first", data)),
            owner="first-plugin",
        )
        event_bus.subscribe(
            "status.changed",
            lambda data: calls.append(("second", data)),
            owner="second-plugin",
        )

        self.assertTrue(event_bus.unsubscribe_token(first_token))
        event_bus.publish("status.changed", {"value": 1})
        self.assertEqual(calls, [("second", {"value": 1})])
        self.assertEqual(event_bus.unsubscribe_owner("second-plugin"), 1)

        legacy_callback = lambda data: calls.append(("legacy", data))
        event_bus.subscribe("status.changed", legacy_callback)
        self.assertTrue(event_bus.unsubscribe("status.changed", legacy_callback))
        event_bus.publish("status.changed", {"value": 2})
        self.assertEqual(calls, [("second", {"value": 1})])

    def test_background_publish_dispatches_on_event_bus_thread(self):
        event_bus = EventBus()
        callback_threads = []
        delivered = threading.Event()

        def callback(data):
            callback_threads.append(threading.get_ident())
            delivered.set()

        event_bus.subscribe("worker.event", callback)

        worker = threading.Thread(
            target=event_bus.publish,
            args=("worker.event", {"value": 1}),
        )
        worker.start()
        worker.join()
        deadline = time.monotonic() + 1
        while not delivered.is_set() and time.monotonic() < deadline:
            self.app.processEvents()

        self.assertTrue(delivered.is_set())
        self.assertEqual(callback_threads, [threading.get_ident()])


class SchedulerLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_shutdown_timeout_is_bounded_for_running_python_code(self):
        scheduler = PluginScheduler("slow-plugin", max_threads=1)
        started = threading.Event()
        release = threading.Event()

        def blocking_task():
            started.set()
            release.wait(2)

        scheduler.run_async(blocking_task)
        self.assertTrue(started.wait(1))

        try:
            before = time.monotonic()
            completed = scheduler.shutdown(timeout_ms=20)
            elapsed = time.monotonic() - before

            self.assertFalse(completed)
            self.assertLess(elapsed, 0.5)
        finally:
            release.set()
            self.assertTrue(scheduler.shutdown(timeout_ms=1000))

    def test_context_closes_timer_subscription_and_queued_task(self):
        class StateStoreStub:
            def get_plugin_state(self, plugin_id, key, default=None):
                return default

            def set_plugin_state(self, plugin_id, key, value):
                return None

        scheduler = PluginScheduler("owned-plugin", max_threads=1)
        event_bus = EventBus()
        context = PluginContext(
            plugin_id="owned-plugin",
            scheduler=scheduler,
            event_bus=event_bus,
            state_store=StateStoreStub(),
            permissions=["event"],
        )
        state = context.state
        blocker_started = threading.Event()
        release_blocker = threading.Event()
        queued_task_ran = threading.Event()

        def blocking_task():
            blocker_started.set()
            release_blocker.wait(2)

        scheduler.run_async(blocking_task)
        self.assertTrue(blocker_started.wait(1))
        queued_task = context.run_async(queued_task_ran.set)
        timer = context.create_timer()
        timer.start(1000)
        calls = []
        context.subscribe_event("owned.event", calls.append)

        try:
            self.assertTrue(context.close())
            self.assertFalse(context.close())
            self.assertTrue(queued_task.cancelled)
            self.assertFalse(timer.isActive())
            event_bus.publish("owned.event", {"value": 1})
            self.assertEqual(calls, [])
            with self.assertRaises(RuntimeError):
                context.create_timer()
            with self.assertRaises(RuntimeError):
                state.get("after-close")
        finally:
            release_blocker.set()
            self.assertTrue(scheduler.shutdown(timeout_ms=1000))

        self.assertTrue(queued_task.wait(1))
        self.assertFalse(queued_task_ran.is_set())


class PluginRuntimeLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.event_bus = EventBus()
        self.api_registry = ApiRegistry()
        self.runtime = PluginRuntime(
            self.event_bus,
            api_registry=self.api_registry,
        )

    @staticmethod
    def _manifest(plugin_id, *, manifest_version=1):
        manifest = {
            "id": plugin_id,
            "entry": "plugin.py",
            "class": "Plugin",
            "api_version": "1.0",
            "permissions": ["event"],
        }
        if manifest_version == 2:
            manifest["manifest_version"] = 2
        return manifest

    @staticmethod
    def _write_plugin(directory, source):
        Path(directory, "plugin.py").write_text(source, encoding="utf-8")

    def test_unload_releases_context_resources_and_api_routes(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            self._write_plugin(
                plugin_dir,
                """
class Plugin:
    def __init__(self, context):
        self.context = context
        self.events = []
        self.unloaded = False

    def on_load(self):
        self.context.subscribe_event("sample.event", self.events.append)
        self.timer = self.context.create_timer()
        self.timer.start(5000)
        self.context.register_api_route(
            "ping",
            lambda payload, request_context: {"plugin": self.context.plugin_id},
        )

    def on_unload(self):
        self.unloaded = True
""",
            )
            plugin_id = "lifecycle-ok"
            route = f"plugins/{plugin_id}/ping"

            self.assertTrue(
                self.runtime.load_plugin(self._manifest(plugin_id), plugin_dir)
            )
            instance = self.runtime.get_plugin(plugin_id)
            self.event_bus.publish("sample.event", {"value": 1})
            self.assertEqual(instance.events, [{"value": 1}])
            self.assertTrue(self.api_registry.invoke(ApiCaller.core(), route)["ok"])

            self.runtime.unload_plugin(plugin_id)
            self.event_bus.publish("sample.event", {"value": 2})

            self.assertTrue(instance.unloaded)
            self.assertFalse(instance.timer.isActive())
            self.assertEqual(instance.events, [{"value": 1}])
            self.assertEqual(
                self.api_registry.invoke(ApiCaller.core(), route)["code"],
                "SERVICE_UNAVAILABLE",
            )
            self.assertNotIn(plugin_id, self.runtime._contexts)
            self.assertNotIn(plugin_id, self.runtime._schedulers)
            self.assertNotIn(f"plugin_{plugin_id}", sys.modules)
            self.assertNotIn(plugin_dir, sys.path)

    def test_load_failure_rolls_back_partial_plugin(self):
        with tempfile.TemporaryDirectory() as plugin_dir:
            rollback_marker = Path(plugin_dir, "rolled-back.txt")
            self._write_plugin(
                plugin_dir,
                f"""
from pathlib import Path

class Plugin:
    def __init__(self, context):
        self.context = context

    def on_load(self):
        self.context.subscribe_event("broken.event", lambda data: None)
        self.timer = self.context.create_timer()
        self.timer.start(5000)
        self.context.register_api_route(
            "ping",
            lambda payload, request_context: {{"ok": True}},
        )
        raise RuntimeError("load failed intentionally")

    def on_unload(self):
        Path({str(rollback_marker)!r}).write_text("done", encoding="utf-8")
""",
            )
            plugin_id = "lifecycle-broken"
            route = f"plugins/{plugin_id}/ping"

            self.assertFalse(
                self.runtime.load_plugin(self._manifest(plugin_id), plugin_dir)
            )

            self.assertTrue(rollback_marker.exists())
            self.assertIsNone(self.runtime.get_plugin(plugin_id))
            self.assertNotIn(plugin_id, self.runtime._contexts)
            self.assertNotIn(plugin_id, self.runtime._schedulers)
            self.assertNotIn(f"plugin_{plugin_id}", sys.modules)
            self.assertNotIn(plugin_dir, sys.path)
            self.assertEqual(self.event_bus.unsubscribe_owner(plugin_id), 0)
            self.assertEqual(
                self.api_registry.invoke(ApiCaller.core(), route)["code"],
                "SERVICE_UNAVAILABLE",
            )

    def test_v2_plugin_uses_isolated_package_namespace_and_cleans_submodules(self):
        with (
            tempfile.TemporaryDirectory() as first_dir,
            tempfile.TemporaryDirectory() as second_dir,
        ):
            Path(first_dir, "helper.py").write_text(
                'VALUE = "first"\n', encoding="utf-8"
            )
            Path(second_dir, "helper.py").write_text(
                'VALUE = "second"\n', encoding="utf-8"
            )
            source = """
from .helper import VALUE

class Plugin:
    def __init__(self, context):
        self.value = VALUE

    def on_load(self):
        pass

    def on_unload(self):
        pass
"""
            self._write_plugin(first_dir, source)
            self._write_plugin(second_dir, source)

            self.assertTrue(
                self.runtime.load_plugin(
                    self._manifest("isolated-first", manifest_version=2),
                    first_dir,
                )
            )
            self.assertTrue(
                self.runtime.load_plugin(
                    self._manifest("isolated-second", manifest_version=2),
                    second_dir,
                )
            )
            self.assertEqual(self.runtime.get_plugin("isolated-first").value, "first")
            self.assertEqual(self.runtime.get_plugin("isolated-second").value, "second")
            self.assertNotIn(first_dir, sys.path)
            self.assertNotIn(second_dir, sys.path)

            first_prefix = self.runtime._module_names["isolated-first"]
            second_prefix = self.runtime._module_names["isolated-second"]
            self.assertIn(f"{first_prefix}.helper", sys.modules)
            self.assertIn(f"{second_prefix}.helper", sys.modules)

            self.runtime.unload_plugin("isolated-first")
            self.assertFalse(
                any(
                    name == first_prefix or name.startswith(f"{first_prefix}.")
                    for name in sys.modules
                )
            )
            self.assertIn(f"{second_prefix}.helper", sys.modules)
            self.runtime.unload_plugin("isolated-second")

    def test_declared_plugins_collaborate_through_commands_and_events(self):
        with (
            tempfile.TemporaryDirectory() as provider_dir,
            tempfile.TemporaryDirectory() as consumer_dir,
        ):
            self._write_plugin(
                provider_dir,
                """
class Plugin:
    def __init__(self, context):
        self.context = context
        self.value = 0

    def on_load(self):
        self.context.register_api_route(
            "set-value",
            self.set_value,
            version="2.1",
            exported_capability="provider.write",
        )

    def set_value(self, payload, request_context):
        self.value = payload["value"]
        self.context.publish_event("changed", {"value": self.value})
        return {"value": self.value}

    def on_unload(self):
        pass
""",
            )
            self._write_plugin(
                consumer_dir,
                """
class Plugin:
    def __init__(self, context):
        self.context = context
        self.events = []

    def on_load(self):
        self.context.subscribe_plugin_event(
            "provider",
            "changed",
            self.events.append,
        )
        self.result = self.context.call_plugin(
            "provider",
            "set-value",
            {"value": 7},
            version="2.0",
        )

    def on_unload(self):
        pass
""",
            )
            provider_manifest = self._manifest("provider", manifest_version=2)
            provider_manifest["permissions"] = ["event"]
            consumer_manifest = self._manifest("consumer", manifest_version=2)
            consumer_manifest.update(
                {
                    "capabilities": ["provider.write"],
                    "dependencies": {"plugins": {"provider": ">=1"}},
                    "permissions": ["event"],
                }
            )

            self.assertTrue(self.runtime.load_plugin(provider_manifest, provider_dir))
            self.assertTrue(self.runtime.load_plugin(consumer_manifest, consumer_dir))
            consumer = self.runtime.get_plugin("consumer")
            self.assertEqual(consumer.result, {"value": 7})
            self.assertEqual(consumer.events, [{"value": 7}])
            with self.assertRaises(PermissionError):
                consumer.context.call_plugin("undeclared", "read")

            self.runtime.unload_plugin("consumer")
            self.runtime.unload_plugin("provider")


if __name__ == "__main__":
    unittest.main()
