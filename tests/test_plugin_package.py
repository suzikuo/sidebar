import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.plugin_system.plugin_package import (
    PackageLimits,
    PluginPackageError,
    inspect_plugin_package,
    is_safe_plugin_id,
    stage_plugin_package,
)
from tests.pe_test_utils import MACHINE_ARM64, build_test_pe


class PluginPackageTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _manifest(self, **overrides):
        manifest = {
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "1.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
        }
        manifest.update(overrides)
        return manifest

    def _write_package(self, filename="sample.atplugin", members=None):
        package_path = self.root / filename
        if members is None:
            members = {
                "manifest.json": json.dumps(self._manifest()),
                "plugin.py": "class SamplePlugin: pass\n",
            }
        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in members.items():
                if isinstance(name, zipfile.ZipInfo):
                    archive.writestr(name, content)
                else:
                    archive.writestr(name, content)
        return package_path

    def _v2_manifest(self, files, **overrides):
        manifest = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "1.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
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
                path: self._sha256(content) for path, content in files.items()
            },
            "requires_restart": False,
        }
        manifest.update(overrides)
        return manifest

    @staticmethod
    def _sha256(content: bytes | str) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def _assert_package_error(self, code, callback):
        with self.assertRaises(PluginPackageError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_valid_atplugin_is_inspected_and_staged_without_extractall(self):
        plugin_source = "class SamplePlugin: pass\n"
        asset_source = "console.log('ok')"
        package_path = self._write_package(
            members={
                "manifest.json": json.dumps(
                    self._v2_manifest(
                        {
                            "src/plugin.py": plugin_source,
                            "assets/app.js": asset_source,
                        },
                        entry="src/plugin.py",
                    )
                ),
                "src/plugin.py": plugin_source,
                "assets/app.js": asset_source,
            }
        )

        info = inspect_plugin_package(package_path)
        staged = stage_plugin_package(package_path, self.root / "staging")

        self.assertEqual(info.plugin_id, "sample_plugin")
        self.assertFalse(info.legacy_zip)
        self.assertEqual(info.normalized_manifest.plugin_id, "sample_plugin")
        self.assertEqual(staged.info.manifest["entry"], "src/plugin.py")
        self.assertTrue(staged.staging_path.is_dir())
        self.assertEqual(
            (staged.staging_path / "src" / "plugin.py").read_text(encoding="utf-8"),
            "class SamplePlugin: pass\n",
        )
        self.assertTrue((staged.staging_path / "manifest.json").is_file())

    def test_atplugin_rejects_legacy_manifest_with_stable_error(self):
        manifests = (
            self._manifest(),
            {"id": "incomplete_legacy_plugin"},
            {**self._manifest(), "manifest_version": 1},
        )
        for index, manifest in enumerate(manifests):
            with self.subTest(manifest=manifest):
                package_path = self._write_package(
                    f"legacy-v1-{index}.atplugin",
                    {
                        "manifest.json": json.dumps(manifest),
                        "plugin.py": "class SamplePlugin: pass\n",
                    },
                )
                self._assert_package_error(
                    "MANIFEST_V2_REQUIRED",
                    lambda path=package_path: inspect_plugin_package(path),
                )

    def test_legacy_zip_requires_opt_in_and_strips_single_wrapper(self):
        package_path = self._write_package(
            "sample.zip",
            {
                "sample/manifest.json": json.dumps(self._manifest()),
                "sample/plugin.py": "class SamplePlugin: pass\n",
            },
        )

        self._assert_package_error(
            "UNSUPPORTED_PACKAGE_TYPE",
            lambda: inspect_plugin_package(package_path),
        )
        staged = stage_plugin_package(
            package_path,
            self.root / "staging",
            allow_legacy_zip=True,
        )

        self.assertTrue(staged.info.legacy_zip)
        self.assertEqual(staged.info.content_prefix, "sample/")
        self.assertTrue((staged.staging_path / "plugin.py").is_file())
        self.assertFalse((staged.staging_path / "sample").exists())

    def test_atplugin_requires_manifest_at_archive_root(self):
        package_path = self._write_package(
            members={
                "sample/manifest.json": json.dumps(self._manifest()),
                "sample/plugin.py": "pass",
            }
        )

        self._assert_package_error(
            "MANIFEST_NOT_FOUND", lambda: inspect_plugin_package(package_path)
        )

    def test_plugin_id_uses_stable_safe_character_set(self):
        self.assertTrue(is_safe_plugin_id("bookmarks.card-v2"))
        invalid_ids = (
            "Plugin",
            "2plugin",
            "../plugin",
            "plugin..child",
            "plugin_",
            "a" * 65,
        )
        for index, plugin_id in enumerate(invalid_ids):
            with self.subTest(plugin_id=plugin_id):
                package_path = self._write_package(
                    f"invalid-id-{index}.zip",
                    {
                        "manifest.json": json.dumps(
                            self._manifest(id=plugin_id)
                        ),
                        "plugin.py": "pass",
                    },
                )
                self._assert_package_error(
                    "INVALID_PLUGIN_ID",
                    lambda path=package_path: inspect_plugin_package(
                        path, allow_legacy_zip=True
                    ),
                )

    def test_absolute_and_traversal_archive_paths_are_rejected(self):
        for index, unsafe_path in enumerate(
            ("../escape.py", "dir/../../escape.py", "dir\\..\\escape.py", "C:/escape.py")
        ):
            with self.subTest(path=unsafe_path):
                package_path = self._write_package(
                    f"unsafe-{index}.atplugin",
                    {
                        "manifest.json": json.dumps(self._manifest()),
                        "plugin.py": "pass",
                        unsafe_path: "escape",
                    },
                )
                self._assert_package_error(
                    "UNSAFE_PATH",
                    lambda path=package_path: inspect_plugin_package(path),
                )

    def test_symbolic_links_and_reparse_points_are_rejected(self):
        symlink = zipfile.ZipInfo("link.py")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        reparse = zipfile.ZipInfo("reparse.py")
        reparse.create_system = 0
        reparse.external_attr = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

        for index, special_member in enumerate((symlink, reparse)):
            with self.subTest(member=special_member.filename):
                package_path = self._write_package(
                    f"link-{index}.atplugin",
                    {
                        "manifest.json": json.dumps(self._manifest()),
                        "plugin.py": "pass",
                        special_member: "target.py",
                    },
                )
                self._assert_package_error(
                    "LINK_NOT_ALLOWED",
                    lambda path=package_path: inspect_plugin_package(path),
                )

    def test_entry_count_and_uncompressed_size_limits_are_enforced(self):
        package_path = self._write_package()

        self._assert_package_error(
            "TOO_MANY_ENTRIES",
            lambda: inspect_plugin_package(
                package_path,
                limits=PackageLimits(
                    max_entries=1,
                    max_uncompressed_size=1024,
                    max_manifest_size=1024,
                ),
            ),
        )
        self._assert_package_error(
            "PACKAGE_TOO_LARGE",
            lambda: inspect_plugin_package(
                package_path,
                limits=PackageLimits(
                    max_entries=10,
                    max_uncompressed_size=8,
                    max_manifest_size=1024,
                ),
            ),
        )

    def test_manifest_entry_must_be_safe_supported_and_present(self):
        cases = (
            ("../plugin.py", "INVALID_ENTRY"),
            ("missing.py", "ENTRY_NOT_FOUND"),
            ("dist/index.html", "INVALID_ENTRY"),
        )
        for index, (entry, expected_code) in enumerate(cases):
            with self.subTest(entry=entry):
                package_path = self._write_package(
                    f"entry-{index}.zip",
                    {
                        "manifest.json": json.dumps(self._manifest(entry=entry)),
                        "plugin.py": "pass",
                    },
                )
                self._assert_package_error(
                    expected_code,
                    lambda path=package_path: inspect_plugin_package(
                        path, allow_legacy_zip=True
                    ),
                )

    def test_manifest_core_fields_use_shared_typed_validation(self):
        cases = (
            ({"class": "Not.Valid"}, "INVALID_PLUGIN_CLASS"),
            ({"version": "not a version"}, "INVALID_PLUGIN_VERSION"),
            ({"api_version": "1"}, "INVALID_API_VERSION"),
        )
        for index, (overrides, expected_code) in enumerate(cases):
            with self.subTest(expected_code=expected_code):
                package_path = self._write_package(
                    f"manifest-core-{index}.zip",
                    {
                        "manifest.json": json.dumps(self._manifest(**overrides)),
                        "plugin.py": "class SamplePlugin: pass\n",
                    },
                )
                self._assert_package_error(
                    expected_code,
                    lambda path=package_path: inspect_plugin_package(
                        path, allow_legacy_zip=True
                    ),
                )

    def test_v2_file_hashes_and_native_declarations_are_enforced(self):
        plugin_source = "class SamplePlugin: pass\n"
        native_content = build_test_pe()
        native_path = "sample/fast.cp311-win_amd64.pyd"
        manifest = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "1.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1,<2",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {"host": [], "python": []},
            "ui": {"type": "native"},
            "native_modules": [
                {
                    "module": "sample.fast",
                    "path": native_path,
                    "sha256": self._sha256(native_content),
                }
            ],
            "files": {
                "plugin.py": self._sha256(plugin_source),
                native_path: self._sha256(native_content),
            },
            "requires_restart": True,
        }
        package = self._write_package(
            "v2-native.atplugin",
            {
                "manifest.json": json.dumps(manifest),
                "plugin.py": plugin_source,
                native_path: native_content,
            },
        )

        info = inspect_plugin_package(package)

        self.assertEqual(info.normalized_manifest.native_modules[0].module, "sample.fast")

    def test_v2_native_pe_machine_and_init_export_are_enforced(self):
        plugin_source = "class SamplePlugin: pass\n"
        native_path = "sample/fast.cp311-win_amd64.pyd"
        cases = (
            (
                "wrong-machine.atplugin",
                build_test_pe(machine=MACHINE_ARM64),
                "NATIVE_MACHINE_MISMATCH",
            ),
            (
                "wrong-export.atplugin",
                build_test_pe(export_name="PyInit_other"),
                "NATIVE_INIT_SYMBOL_MISSING",
            ),
            (
                "invalid-pe.atplugin",
                b"native-placeholder",
                "INVALID_PE_FILE",
            ),
        )
        for filename, native_content, expected_code in cases:
            with self.subTest(code=expected_code):
                native_hash = self._sha256(native_content)
                manifest = {
                    "manifest_version": 2,
                    "id": "sample_plugin",
                    "name": "Sample Plugin",
                    "version": "1.0.0",
                    "entry": "plugin.py",
                    "class": "SamplePlugin",
                    "api_version": "1.0",
                    "compatibility": {
                        "app": ">=1,<2",
                        "python_abi": "cp311",
                        "platform": "win_amd64",
                    },
                    "dependencies": {"host": [], "python": []},
                    "ui": {"type": "native"},
                    "native_modules": [
                        {
                            "module": "sample.fast",
                            "path": native_path,
                            "sha256": native_hash,
                        }
                    ],
                    "files": {
                        "plugin.py": self._sha256(plugin_source),
                        native_path: native_hash,
                    },
                    "requires_restart": True,
                }
                package = self._write_package(
                    filename,
                    {
                        "manifest.json": json.dumps(manifest),
                        "plugin.py": plugin_source,
                        native_path: native_content,
                    },
                )

                self._assert_package_error(
                    expected_code,
                    lambda path=package: inspect_plugin_package(path),
                )

    def test_v2_rejects_hash_mismatch_undeclared_files_and_wrong_native_tag(self):
        plugin_source = "class SamplePlugin: pass\n"
        base = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "1.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1,<2",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {"host": [], "python": []},
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {"plugin.py": self._sha256(plugin_source)},
            "requires_restart": True,
        }
        cases = []

        bad_hash = dict(base)
        bad_hash["files"] = {"plugin.py": "0" * 64}
        cases.append(
            (
                "bad-hash.atplugin",
                bad_hash,
                {"plugin.py": plugin_source},
                "FILE_HASH_MISMATCH",
            )
        )

        cases.append(
            (
                "undeclared.atplugin",
                base,
                {"plugin.py": plugin_source, "extra.txt": "extra"},
                "UNDECLARED_PACKAGE_FILE",
            )
        )

        wrong_native_content = b"native"
        wrong_native_path = "sample/fast.cp312-win_amd64.pyd"
        wrong_tag = dict(base)
        wrong_tag["native_modules"] = [
            {
                "module": "sample.fast",
                "path": wrong_native_path,
                "sha256": self._sha256(wrong_native_content),
            }
        ]
        wrong_tag["files"] = {
            "plugin.py": self._sha256(plugin_source),
            wrong_native_path: self._sha256(wrong_native_content),
        }
        cases.append(
            (
                "wrong-tag.atplugin",
                wrong_tag,
                {
                    "plugin.py": plugin_source,
                    wrong_native_path: wrong_native_content,
                },
                "NATIVE_MODULE_TAG_MISMATCH",
            )
        )

        for filename, manifest, members, code in cases:
            with self.subTest(code=code):
                package = self._write_package(
                    filename,
                    {"manifest.json": json.dumps(manifest), **members},
                )
                self._assert_package_error(
                    code,
                    lambda path=package: inspect_plugin_package(path),
                )

    def test_case_insensitive_duplicate_paths_are_rejected(self):
        package_path = self._write_package(
            members={
                "manifest.json": json.dumps(self._manifest()),
                "plugin.py": "pass",
                "PLUGIN.py": "duplicate",
            }
        )

        self._assert_package_error(
            "DUPLICATE_PATH", lambda: inspect_plugin_package(package_path)
        )

    def test_legacy_wrapper_cannot_have_sibling_content(self):
        package_path = self._write_package(
            "sample.zip",
            {
                "sample/manifest.json": json.dumps(self._manifest()),
                "sample/plugin.py": "pass",
                "outside.txt": "not part of plugin",
            },
        )

        self._assert_package_error(
            "INVALID_LAYOUT",
            lambda: inspect_plugin_package(package_path, allow_legacy_zip=True),
        )


if __name__ == "__main__":
    unittest.main()
