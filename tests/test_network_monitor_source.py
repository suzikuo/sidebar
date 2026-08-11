import unittest
from pathlib import Path

from core.plugin_system.manifest_loader import ManifestLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugins" / "network_monitor"


class NetworkMonitorSourceTest(unittest.TestCase):
    def test_unsealed_plugin_source_passes_full_integrity_validation(self):
        self.assertIsNone(
            ManifestLoader.load_with_model(
                str(PLUGIN_ROOT),
                log_errors=False,
            )
        )

        loaded = ManifestLoader.load_with_model(
            str(PLUGIN_ROOT),
            log_errors=False,
            allow_unsealed=True,
        )

        self.assertIsNotNone(loaded)
        raw, manifest = loaded
        self.assertEqual(manifest.plugin_id, "network_monitor")
        self.assertEqual(manifest.dependencies.lock, "dependencies.lock.json")
        self.assertEqual(
            tuple(item.requirement for item in manifest.dependencies.python),
            ("pywintrace==0.2.0",),
        )
        self.assertTrue(manifest.requires_restart)
        self.assertIn("plugin.py", raw["files"])
        self.assertIn("collector.py", raw["files"])
        self.assertIn("floating.py", raw["files"])
        self.assertIn("wheels/pywintrace-0.2.0-py3-none-any.whl", raw["files"])
        self.assertIn("dependencies.lock.json", raw["files"])


if __name__ == "__main__":
    unittest.main()
