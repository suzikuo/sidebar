import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

from packaging.version import Version

from core.control_center.catalog import PluginCatalogService
from core.plugin_system.plugin_manifest import PluginManifestError


def _manifest(plugin_id, version, *, extensions=None):
    return SimpleNamespace(
        plugin_id=plugin_id,
        name=plugin_id.replace("_", " ").title(),
        version=Version(version),
        author="Agile Tiles",
        description="Plugin description",
        extensions=MappingProxyType(extensions or {}),
    )


def _status(plugin_id, version="1.0.0"):
    return SimpleNamespace(
        plugin_id=plugin_id,
        name=plugin_id,
        selected_version=version,
        source="user",
        enabled=True,
        user_present=True,
        user_version=version,
        transaction=None,
        can_uninstall=True,
        can_rollback=False,
        restart_required=False,
        loaded=True,
    )


class _Manager:
    host_environment = object()

    def __init__(self, statuses=()):
        self._statuses = tuple(statuses)

    def get_plugin_statuses(self):
        return self._statuses


class PluginCatalogServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    @patch("core.control_center.catalog.check_compatibility")
    @patch("core.control_center.catalog.inspect_plugin_package")
    def test_catalog_selects_latest_package_and_merges_installed_state(
        self, inspect_package, _
    ):
        old_path = self.root / "sample-old.atplugin"
        new_path = self.root / "sample.atplugin"
        old_path.write_bytes(b"old")
        new_path.write_bytes(b"new")
        infos = {
            old_path.name: SimpleNamespace(
                plugin_id="sample",
                package_path=old_path,
                normalized_manifest=_manifest("sample", "1.0.0"),
            ),
            new_path.name: SimpleNamespace(
                plugin_id="sample",
                package_path=new_path,
                normalized_manifest=_manifest(
                    "sample", "2.0.0", extensions={"marketplace": {"category": "效率"}}
                ),
            ),
        }
        inspect_package.side_effect = lambda path: infos[path.name]
        service = PluginCatalogService(
            [self.root],
            _Manager([_status("sample", "1.0.0")]),
        )

        snapshot = service.snapshot()

        self.assertEqual(len(snapshot["entries"]), 1)
        self.assertEqual(snapshot["entries"][0]["version"], "2.0.0")
        self.assertEqual(snapshot["entries"][0]["action"], "update")
        self.assertEqual(snapshot["entries"][0]["category"], "效率")
        self.assertEqual(service.package_path("sample"), new_path)

    @patch("core.control_center.catalog.check_compatibility")
    @patch("core.control_center.catalog.inspect_plugin_package")
    def test_incompatible_package_cannot_be_resolved_for_install(
        self, inspect_package, compatibility
    ):
        package_path = self.root / "sample.atplugin"
        package_path.write_bytes(b"package")
        inspect_package.return_value = SimpleNamespace(
            plugin_id="sample",
            package_path=package_path,
            normalized_manifest=_manifest("sample", "1.0.0"),
        )
        compatibility.side_effect = PluginManifestError(
            "INCOMPATIBLE_APP_VERSION", "Requires a newer app."
        )
        service = PluginCatalogService([self.root], _Manager())

        entry = service.snapshot()["entries"][0]

        self.assertEqual(entry["action"], "incompatible")
        self.assertEqual(entry["compatibilityCode"], "INCOMPATIBLE_APP_VERSION")
        self.assertIsNone(service.package_path("sample"))


if __name__ == "__main__":
    unittest.main()
