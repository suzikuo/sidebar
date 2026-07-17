import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from plugin_packer import PluginPackerError, build_plugin_package, main
from core.plugin_system.plugin_package import inspect_plugin_package
from tests.pe_test_utils import build_test_pe


def _manifest(*, native_modules=None, requires_restart=False):
    return {
        "manifest_version": 2,
        "id": "sample_plugin",
        "name": "Sample Plugin",
        "version": "1.2.3",
        "entry": "plugin.py",
        "class": "SamplePlugin",
        "api_version": "1.0",
        "compatibility": {
            "app": ">=1.0",
            "python_abi": "cp311",
            "platform": "win_amd64",
        },
        "dependencies": {"host": [], "python": []},
        "files": {},
        "native_modules": native_modules or [],
        "requires_restart": requires_restart,
        "ui": {"type": "native"},
    }


class PluginPackerTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.plugin_root = self.root / "plugin"
        self.plugin_root.mkdir()
        self.plugin_source = b"class SamplePlugin:\n    pass\n"
        (self.plugin_root / "plugin.py").write_bytes(self.plugin_source)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _write_manifest(self, manifest=None):
        value = manifest or _manifest()
        (self.plugin_root / "manifest.json").write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return value

    @staticmethod
    def _archive_manifest(package_path):
        with zipfile.ZipFile(package_path, "r") as archive:
            return json.loads(archive.read("manifest.json"))

    def test_builds_root_layout_package_from_empty_files_placeholder(self):
        source_manifest = self._write_manifest()
        asset = self.plugin_root / "assets" / "message.txt"
        asset.parent.mkdir()
        asset.write_text("hello", encoding="utf-8")

        package_path = build_plugin_package(self.plugin_root, self.root / "output")

        self.assertEqual(package_path.name, "plugin.atplugin")
        inspected = inspect_plugin_package(package_path)
        self.assertEqual(inspected.plugin_id, "sample_plugin")
        with zipfile.ZipFile(package_path, "r") as archive:
            names = set(archive.namelist())
        self.assertEqual(names, {"manifest.json", "plugin.py", "assets/message.txt"})

        generated = self._archive_manifest(package_path)
        self.assertEqual(
            generated["files"],
            {
                "assets/message.txt": hashlib.sha256(b"hello").hexdigest(),
                "plugin.py": hashlib.sha256(self.plugin_source).hexdigest(),
            },
        )
        self.assertEqual(source_manifest["files"], {})
        self.assertEqual(json.loads((self.plugin_root / "manifest.json").read_text(
            encoding="utf-8"
        ))["files"], {})

    def test_ignores_only_bytecode_caches_and_the_output_package_itself(self):
        self._write_manifest()
        cache = self.plugin_root / "__pycache__"
        cache.mkdir()
        (cache / "plugin.cpython-311.pyc").write_bytes(b"cache")
        (self.plugin_root / "ignored.pyc").write_bytes(b"cache")
        (self.plugin_root / "ignored.pyo").write_bytes(b"cache")
        (self.plugin_root / "keep.tmp").write_bytes(b"keep")

        first = build_plugin_package(self.plugin_root, self.plugin_root)
        second = build_plugin_package(self.plugin_root, self.plugin_root)

        self.assertEqual(first, second)
        generated = self._archive_manifest(second)
        self.assertEqual(set(generated["files"]), {"keep.tmp", "plugin.py"})
        with zipfile.ZipFile(second, "r") as archive:
            names = set(archive.namelist())
        self.assertNotIn(second.name, names)
        self.assertFalse(any("__pycache__" in name for name in names))

    def test_synchronizes_native_module_hash_before_self_validation(self):
        native_path = self.plugin_root / "native" / "fast.cp311-win_amd64.pyd"
        native_path.parent.mkdir()
        native_payload = build_test_pe("PyInit_fast")
        native_path.write_bytes(native_payload)
        manifest = _manifest(
            native_modules=[
                {
                    "module": "native.fast",
                    "path": "native/fast.cp311-win_amd64.pyd",
                    "sha256": "0" * 64,
                }
            ],
            requires_restart=True,
        )
        self._write_manifest(manifest)

        package_path = build_plugin_package(self.plugin_root, self.root / "output")

        generated = self._archive_manifest(package_path)
        expected_hash = hashlib.sha256(native_payload).hexdigest()
        self.assertEqual(generated["native_modules"][0]["sha256"], expected_hash)
        self.assertEqual(
            generated["files"]["native/fast.cp311-win_amd64.pyd"],
            expected_hash,
        )
        inspect_plugin_package(package_path)

    def test_rejects_legacy_manifest_and_cli_returns_nonzero(self):
        legacy = {
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "1.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
        }
        self._write_manifest(legacy)

        with self.assertRaises(PluginPackerError):
            build_plugin_package(self.plugin_root, self.root / "output")

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main([str(self.plugin_root), "--out", str(self.root / "output")])
        self.assertNotEqual(exit_code, 0)
        self.assertIn("manifest_version 2", stderr.getvalue())
        self.assertFalse((self.root / "output" / "plugin.atplugin").exists())

    def test_repository_hello_template_builds_as_strict_v2_package(self):
        template_root = Path(__file__).resolve().parents[1] / "templates" / "hello_plugin"
        output_root = self.root / "output"

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([str(template_root), "--out", str(output_root)])

        self.assertEqual(exit_code, 0)
        package_path = output_root / "hello_plugin.atplugin"
        self.assertIn(str(package_path), stdout.getvalue())
        inspected = inspect_plugin_package(package_path)
        self.assertEqual(inspected.plugin_id, "hello_plugin")
        self.assertEqual(inspected.normalized_manifest.manifest_version, 2)
        self.assertIn("plugin.py", inspected.normalized_manifest.file_hashes)


if __name__ == "__main__":
    unittest.main()
