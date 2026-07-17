import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from core.plugin_system.plugin_integrity import (
    hash_plugin_directory,
    purge_plugin_bytecode_caches,
    validate_plugin_directory,
)
from core.plugin_system.plugin_manifest import PluginManifestError, parse_manifest
from tests.pe_test_utils import build_test_pe


class PluginDirectoryIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.plugin_source = "class Plugin: pass\n"
        self.manifest_data = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "1.0.0",
            "entry": "plugin.py",
            "class": "Plugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1,<2",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {"host": [], "python": []},
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {
                "plugin.py": hashlib.sha256(
                    self.plugin_source.encode("utf-8")
                ).hexdigest()
            },
            "requires_restart": True,
        }
        (self.root / "manifest.json").write_text(
            json.dumps(self.manifest_data), encoding="utf-8"
        )
        (self.root / "plugin.py").write_bytes(self.plugin_source.encode("utf-8"))

    def test_valid_directory_passes_and_content_changes_are_rejected(self):
        manifest = parse_manifest(self.manifest_data)

        self.assertIsNone(validate_plugin_directory(self.root, manifest))
        original_digest = hash_plugin_directory(self.root)
        (self.root / "plugin.py").write_bytes(b"tampered\n")

        with self.assertRaises(PluginManifestError) as mismatch:
            validate_plugin_directory(self.root, manifest)
        self.assertEqual(mismatch.exception.code, "FILE_HASH_MISMATCH")
        self.assertNotEqual(hash_plugin_directory(self.root), original_digest)

    def test_undeclared_files_are_rejected(self):
        (self.root / "extra.txt").write_text("extra", encoding="utf-8")

        with self.assertRaises(PluginManifestError) as undeclared:
            validate_plugin_directory(self.root, parse_manifest(self.manifest_data))

        self.assertEqual(undeclared.exception.code, "UNDECLARED_PACKAGE_FILE")

    def test_bytecode_cache_is_ignored_then_removed_before_execution(self):
        cache = self.root / "__pycache__"
        cache.mkdir()
        cached_file = cache / "plugin.cpython-311.pyc"
        cached_file.write_bytes(b"cached bytecode")
        manifest = parse_manifest(self.manifest_data)

        self.assertIsNone(validate_plugin_directory(self.root, manifest))
        purge_plugin_bytecode_caches(self.root)

        self.assertFalse(cache.exists())

    def test_native_pe_is_validated_without_loading_it(self):
        native_path = "sample/fast.cp311-win_amd64.pyd"
        native_file = self.root.joinpath(*native_path.split("/"))
        native_file.parent.mkdir(parents=True)
        invalid_native = build_test_pe(export_name="PyInit_other")
        native_file.write_bytes(invalid_native)
        native_hash = hashlib.sha256(invalid_native).hexdigest()
        self.manifest_data["native_modules"] = [
            {
                "module": "sample.fast",
                "path": native_path,
                "sha256": native_hash,
            }
        ]
        self.manifest_data["files"][native_path] = native_hash

        with self.assertRaises(PluginManifestError) as invalid:
            validate_plugin_directory(
                self.root,
                parse_manifest(self.manifest_data),
            )

        self.assertEqual(invalid.exception.code, "NATIVE_INIT_SYMBOL_MISSING")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support unavailable")
    def test_links_are_rejected_when_the_platform_allows_creation(self):
        link = self.root / "linked.py"
        try:
            os.symlink(self.root / "plugin.py", link)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        self.manifest_data["files"]["linked.py"] = self.manifest_data["files"][
            "plugin.py"
        ]

        with self.assertRaises(PluginManifestError) as unsafe:
            validate_plugin_directory(self.root, parse_manifest(self.manifest_data))

        self.assertEqual(unsafe.exception.code, "UNSAFE_PLUGIN_FILE")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support unavailable")
    def test_plugin_root_link_is_rejected_before_resolution(self):
        linked_root = self.root.parent / f"{self.root.name}-linked"
        try:
            os.symlink(self.root, linked_root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlink creation unavailable: {error}")
        self.addCleanup(linked_root.unlink, missing_ok=True)

        with self.assertRaises(PluginManifestError) as unsafe:
            validate_plugin_directory(
                linked_root,
                parse_manifest(self.manifest_data),
            )

        self.assertEqual(unsafe.exception.code, "UNSAFE_PLUGIN_FILE")


if __name__ == "__main__":
    unittest.main()
