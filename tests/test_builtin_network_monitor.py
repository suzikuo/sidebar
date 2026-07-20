import unittest
from pathlib import Path

from core.plugin_system.manifest_loader import ManifestLoader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "builtin_plugins" / "network_monitor"


class BuiltinNetworkMonitorTest(unittest.TestCase):
    def test_unsealed_builtin_source_passes_full_integrity_validation(self):
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
        self.assertIsNone(manifest.dependencies.lock)
        self.assertEqual(manifest.dependencies.python, ())
        self.assertFalse(manifest.requires_restart)
        self.assertIn("plugin.py", raw["files"])
        self.assertIn("collector.py", raw["files"])
        self.assertIn("floating.py", raw["files"])
        self.assertFalse(any(path.startswith("wheels/") for path in raw["files"]))
        self.assertNotIn("dependencies.lock.json", raw["files"])


if __name__ == "__main__":
    unittest.main()
