import ast
import json
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from core.api_gateway import ApiRegistry
from core.plugin_system.event_bus import EventBus
from core.plugin_system.manifest_loader import ManifestLoader
from core.plugin_system.plugin_runtime import PluginRuntime
from core.state_store import StateStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_IDS = (
    "command_palette",
    "system_monitor",
    "windows_controls",
    "backup_restore",
    "plugin_diagnostics",
)


class EssentialPluginArchitectureTest(unittest.TestCase):
    def test_features_live_only_in_independent_plugin_packages(self):
        application_source = (PROJECT_ROOT / "app" / "application.py").read_text(
            encoding="utf-8"
        )
        for plugin_id in PLUGIN_IDS:
            with self.subTest(plugin=plugin_id):
                plugin_dir = PROJECT_ROOT / "plugins" / plugin_id
                self.assertTrue((plugin_dir / "manifest.json").is_file())
                self.assertTrue((plugin_dir / "plugin.py").is_file())
                self.assertNotIn(plugin_id, application_source)
                loaded = ManifestLoader.load_with_model_or_raise(
                    str(plugin_dir),
                    allow_unsealed=True,
                )
                self.assertEqual(loaded[1].plugin_id, plugin_id)
                self.assertEqual(loaded[1].manifest_version, 2)

    def test_plugin_entries_do_not_eagerly_import_views(self):
        for plugin_id in PLUGIN_IDS:
            relative = f"plugins/{plugin_id}/plugin.py"
            tree = ast.parse(
                (PROJECT_ROOT / relative).read_text(encoding="utf-8"),
                filename=relative,
            )
            top_level_imports = {
                f"{'.' * node.level}{node.module or ''}"
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
            }
            self.assertNotIn(".views", top_level_imports)


class EssentialPluginLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_each_plugin_loads_builds_one_view_and_unloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = StateStore(
                str(Path(temp_dir) / "state.json"),
                save_delay_seconds=60,
            )
            runtime = PluginRuntime(EventBus(), store, ApiRegistry())
            try:
                for plugin_id in PLUGIN_IDS:
                    plugin_dir = PROJECT_ROOT / "plugins" / plugin_id
                    manifest = json.loads(
                        (plugin_dir / "manifest.json").read_text(encoding="utf-8")
                    )
                    self.assertTrue(
                        runtime.load_plugin(manifest, str(plugin_dir)),
                        runtime.load_errors.get(plugin_id),
                    )

                for plugin_id in PLUGIN_IDS:
                    with self.subTest(plugin=plugin_id):
                        instance = runtime.get_plugin(plugin_id)
                        first = instance.get_card_widget()
                        second = instance.get_card_widget()
                        self.assertIsInstance(first, QWidget)
                        self.assertIs(first, second)
            finally:
                for plugin_id in reversed(PLUGIN_IDS):
                    runtime.unload_plugin(plugin_id)
                store.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
