import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.plugin_system.event_bus import EventBus
from core.plugin_system.host_environment import build_host_environment
from core.plugin_system.plugin_manager import PluginManager
from core.plugin_system.plugin_package import stage_plugin_package
from core.state_store import StateStore
from plugin_packer import build_plugin_package


class PluginAuthoringFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _manager(self, root: Path, bundled_root: Path, state_store: StateStore):
        return PluginManager(
            [str(bundled_root)],
            EventBus(),
            state_store,
            user_plugins_dir=str(root / "user-plugins"),
            transaction_root=str(root / "plugin-transactions"),
            host_environment=build_host_environment(),
        )

    def test_template_build_update_uninstall_and_bundled_fallback(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "hello_plugin"
            shutil.copytree(project_root / "templates" / "hello_plugin", source)
            package_root = root / "packages"

            bundled_package = build_plugin_package(source, package_root)
            bundled_root = root / "bundled"
            bundled_root.mkdir()
            staged = stage_plugin_package(bundled_package, root / "bundle-staging")
            staged.staging_path.rename(bundled_root / "hello_plugin")

            manifest_path = source / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["version"] = "1.1.0"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            update_package = build_plugin_package(source, package_root)
            state_store = StateStore(str(root / "state.json"))

            manager = self._manager(root, bundled_root, state_store)
            success, _ = manager.install_plugin(str(update_package))
            self.assertTrue(success)
            manager.shutdown()

            updated = self._manager(root, bundled_root, state_store)
            updated.discover_and_load()
            self.assertEqual(updated.get_plugin_source("hello_plugin")["kind"], "user")
            self.assertEqual(
                str(updated.get_manifest_model("hello_plugin").version), "1.1.0"
            )
            self.assertIsNotNone(updated.get_plugin("hello_plugin"))
            queued, _ = updated.queue_uninstall_plugin("hello_plugin")
            self.assertTrue(queued)
            updated.shutdown()

            restored = self._manager(root, bundled_root, state_store)
            restored.discover_and_load()
            self.assertEqual(
                restored.get_plugin_source("hello_plugin")["kind"], "bundled"
            )
            self.assertEqual(
                str(restored.get_manifest_model("hello_plugin").version), "1.0.0"
            )
            self.assertIsNotNone(restored.get_plugin("hello_plugin"))
            restored.shutdown()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
