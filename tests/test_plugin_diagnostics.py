import json
import tempfile
import types
import unittest
from pathlib import Path

from plugins.plugin_diagnostics.collector import DiagnosticCollector, collect_loaded_plugins


class FakeBackend:
    def __init__(self):
        self.values = iter(
            (
                {"cpu_time": 1.0, "working_set": 100, "private_bytes": 120, "handles": 10},
                {"cpu_time": 3.0, "working_set": 110, "private_bytes": 130, "handles": 11},
            )
        )

    def sample(self):
        return next(self.values)


class PluginDiagnosticsTest(unittest.TestCase):
    def test_process_cpu_uses_elapsed_time_and_cpu_count(self):
        clocks = iter((10.0, 12.0))
        collector = DiagnosticCollector(
            backend=FakeBackend(),
            clock=lambda: next(clocks),
            cpu_count=4,
            modules={},
        )

        first = collector.collect()
        second = collector.collect()

        self.assertEqual(first["process"]["cpu_percent"], 0.0)
        self.assertAlmostEqual(second["process"]["cpu_percent"], 25.0)

    def test_loaded_plugin_metadata_comes_from_public_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "manifest.json").write_text(
                json.dumps({"id": "sample", "name": "Sample", "version": "1.2.3"}),
                encoding="utf-8",
            )
            package = types.SimpleNamespace(__path__=[str(root)])
            modules = {
                "_agiletiles_plugin_sample_hash": package,
                "_agiletiles_plugin_sample_hash.plugin": object(),
                "other": object(),
            }

            plugins = collect_loaded_plugins(modules)

            self.assertEqual(len(plugins), 1)
            self.assertEqual(plugins[0]["id"], "sample")
            self.assertEqual(plugins[0]["modules"], 2)


if __name__ == "__main__":
    unittest.main()
