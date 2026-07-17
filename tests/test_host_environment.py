import tempfile
import unittest
from pathlib import Path

from core.plugin_system.host_environment import (
    build_host_environment,
    read_app_version,
)
from core.plugin_system.plugin_manifest import PluginManifestError


class HostEnvironmentTest(unittest.TestCase):
    def test_reads_version_and_builds_current_python_platform_facts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "VERSION").write_text("1.2.3\n", encoding="utf-8")

            self.assertEqual(read_app_version(root), "1.2.3")
            host = build_host_environment(
                app_version="1.2.3",
                host_packages={"Paramiko": "5.0.0"},
            )

            self.assertEqual(str(host.app_version), "1.2.3")
            self.assertEqual(host.python_abi, "cp311")
            self.assertTrue(host.platform_tag.startswith("win_"))
            self.assertEqual(str(host.host_packages["paramiko"]), "5.0.0")

    def test_missing_or_empty_version_is_a_stable_host_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for create_empty in (False, True):
                with self.subTest(create_empty=create_empty):
                    if create_empty:
                        (root / "VERSION").write_text("\n", encoding="utf-8")
                    with self.assertRaises(PluginManifestError) as invalid:
                        read_app_version(root)
                    self.assertEqual(invalid.exception.code, "INVALID_HOST_ENVIRONMENT")
                    if create_empty:
                        (root / "VERSION").unlink()


if __name__ == "__main__":
    unittest.main()
