import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_support.plugin_packages import (
    REPOSITORY_PLUGIN_SOURCE_ROOT,
    build_plugin_packages,
    discover_plugin_package_sources,
)
from core.plugin_system.plugin_package import inspect_plugin_package


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PLUGIN_IDS = {
    "app_launcher",
    "bookmarks.card",
    "gateway_manager",
    "ssh_manager",
    "thiefbook",
    "time",
    "toolbox",
}


class BuiltinPluginPackageTest(unittest.TestCase):
    def test_all_repository_plugins_are_manifest_v2_package_sources(self):
        sources = discover_plugin_package_sources(REPOSITORY_PLUGIN_SOURCE_ROOT)

        self.assertEqual({source.plugin_id for source in sources}, EXPECTED_PLUGIN_IDS)
        for source in sources:
            manifest = (source.source_dir / "manifest.json").read_text(encoding="utf-8")
            self.assertIn('"manifest_version": 2', manifest)
            self.assertIn('"files": {}', manifest)
            for python_file in source.source_dir.rglob("*.py"):
                code = python_file.read_text(encoding="utf-8")
                self.assertNotIn(f"from plugins.{source.source_dir.name}", code)
                self.assertNotIn(f'"plugins.{source.source_dir.name}', code)
                self.assertNotIn(f"'plugins.{source.source_dir.name}", code)

    def test_batch_builds_self_validating_packages_named_by_plugin_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "packages"
            stale = output_dir / "removed.atplugin"
            output_dir.mkdir()
            stale.write_bytes(b"stale")

            packages = build_plugin_packages(
                REPOSITORY_PLUGIN_SOURCE_ROOT, output_dir
            )

            self.assertFalse(stale.exists())
            self.assertEqual({path.stem for path in packages}, EXPECTED_PLUGIN_IDS)
            for package in packages:
                info = inspect_plugin_package(package)
                self.assertEqual(package.stem, info.plugin_id)
                self.assertEqual(info.normalized_manifest.manifest_version, 2)
                self.assertTrue(info.normalized_manifest.file_hashes)

    def test_standalone_build_entry_uses_dist_plugins_by_default(self):
        import build_plugins

        expected = (Path("app_launcher.atplugin"),)
        with patch.object(
            build_plugins, "build_plugin_packages", return_value=expected
        ) as builder:
            result = build_plugins.build()

        self.assertEqual(result, expected)
        builder.assert_called_once_with(
            REPOSITORY_PLUGIN_SOURCE_ROOT, PROJECT_ROOT / "dist" / "plugins"
        )

    def test_failed_batch_keeps_previous_published_packages(self):
        from build_support import plugin_packages

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "packages"
            output_dir.mkdir()
            previous = output_dir / "previous.atplugin"
            previous.write_bytes(b"previous")

            with patch.object(
                plugin_packages,
                "build_plugin_package",
                side_effect=RuntimeError("build failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "build failed"):
                    plugin_packages.build_plugin_packages(
                        REPOSITORY_PLUGIN_SOURCE_ROOT, output_dir
                    )

            self.assertEqual(previous.read_bytes(), b"previous")


if __name__ == "__main__":
    unittest.main()
