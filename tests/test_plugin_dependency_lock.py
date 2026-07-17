import hashlib
import json
import tempfile
import unittest
import zipfile
from dataclasses import FrozenInstanceError
from pathlib import Path

from packaging.version import Version

from core.plugin_system.plugin_dependency_lock import (
    MAX_DEPENDENCY_LOCK_SIZE,
    parse_and_validate_dependency_lock,
    parse_dependency_lock,
    parse_dependency_lock_json,
    validate_dependency_lock,
)
from core.plugin_system.plugin_integrity import validate_plugin_directory
from core.plugin_system.plugin_manifest import (
    PluginManifestError,
    PythonDependencyPolicy,
    check_compatibility,
    parse_manifest,
)
from core.plugin_system.plugin_package import (
    PluginPackageError,
    inspect_plugin_package,
    stage_plugin_package,
)
from tests.test_plugin_wheel import WheelBuilder


class PluginDependencyLockContractTest(unittest.TestCase):
    LOCK_HASH = "1" * 64
    WHEEL_HASH = "2" * 64

    def _manifest_data(self, **overrides):
        data = {
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
            "dependencies": {
                "host": [],
                "python": ["Demo_Package>=2,<3"],
                "lock": "dependencies/lock.json",
            },
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {
                "plugin.py": "0" * 64,
                "dependencies/lock.json": self.LOCK_HASH,
                "dependencies/wheels/demo_package-2.1.0-py3-none-any.whl": (
                    self.WHEEL_HASH
                ),
            },
            "requires_restart": True,
        }
        data.update(overrides)
        return data

    def _lock_data(self, **overrides):
        data = {
            "lock_version": 1,
            "target": {
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "packages": [
                {
                    "name": "Demo.Package",
                    "version": "2.1.0",
                    "wheel": (
                        "dependencies/wheels/"
                        "demo_package-2.1.0-py3-none-any.whl"
                    ),
                    "sha256": self.WHEEL_HASH,
                }
            ],
        }
        data.update(overrides)
        return data

    def assert_lock_error(self, code, callback, field=None):
        with self.assertRaises(PluginManifestError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        if field is not None:
            self.assertEqual(caught.exception.field, field)

    def test_manifest_binds_lock_presence_and_declared_file(self):
        manifest = parse_manifest(self._manifest_data())
        self.assertEqual(manifest.dependencies.lock, "dependencies/lock.json")

        without_lock = self._manifest_data()
        without_lock["dependencies"] = {
            "host": [],
            "python": ["demo-package==2.1.0"],
        }
        self.assert_lock_error(
            "DEPENDENCY_LOCK_REQUIRED",
            lambda: parse_manifest(without_lock),
            "dependencies.lock",
        )

        unnecessary_lock = self._manifest_data()
        unnecessary_lock["dependencies"] = {
            "host": [],
            "python": [],
            "lock": "dependencies/lock.json",
        }
        self.assert_lock_error(
            "UNEXPECTED_DEPENDENCY_LOCK",
            lambda: parse_manifest(unnecessary_lock),
            "dependencies.lock",
        )

        unsafe_lock = self._manifest_data()
        unsafe_lock["dependencies"] = {
            "host": [],
            "python": ["demo-package==2.1.0"],
            "lock": "../lock.json",
        }
        self.assert_lock_error(
            "INVALID_DEPENDENCY_LOCK",
            lambda: parse_manifest(unsafe_lock),
            "dependencies.lock",
        )

        undeclared_lock = self._manifest_data()
        del undeclared_lock["files"]["dependencies/lock.json"]
        self.assert_lock_error(
            "MISSING_FILE_HASH",
            lambda: parse_manifest(undeclared_lock),
            "files",
        )

        wrong_suffix = self._manifest_data()
        wrong_suffix["dependencies"]["lock"] = "dependencies/lock.txt"
        self.assert_lock_error(
            "INVALID_DEPENDENCY_LOCK",
            lambda: parse_manifest(wrong_suffix),
            "dependencies.lock",
        )

        no_restart = self._manifest_data(requires_restart=False)
        self.assert_lock_error(
            "PYTHON_DEPENDENCY_RESTART_REQUIRED",
            lambda: parse_manifest(no_restart),
            "requires_restart",
        )

    def test_lock_is_normalized_typed_and_deeply_immutable(self):
        source = self._lock_data()
        dependency_lock = parse_dependency_lock(source)
        source["packages"][0]["version"] = "9.0"

        self.assertEqual(dependency_lock.lock_version, 1)
        self.assertEqual(dependency_lock.target.python_abi, "cp311")
        self.assertEqual(dependency_lock.packages[0].name, "demo-package")
        self.assertEqual(dependency_lock.packages[0].version, Version("2.1.0"))
        self.assertEqual(
            dependency_lock.raw["packages"][0]["version"],
            "2.1.0",
        )
        with self.assertRaises(FrozenInstanceError):
            dependency_lock.lock_version = 2
        with self.assertRaises(TypeError):
            dependency_lock.raw["target"] = {}

    def test_lock_json_is_bounded_strict_and_rejects_duplicate_keys(self):
        parsed = parse_dependency_lock_json(json.dumps(self._lock_data()))
        self.assertEqual(parsed.packages[0].name, "demo-package")

        self.assert_lock_error(
            "DUPLICATE_DEPENDENCY_LOCK_KEY",
            lambda: parse_dependency_lock_json(
                '{"lock_version":1,"lock_version":1,"target":{},"packages":[]}'
            ),
        )
        self.assert_lock_error(
            "DEPENDENCY_LOCK_TOO_LARGE",
            lambda: parse_dependency_lock_json(
                b" " * (MAX_DEPENDENCY_LOCK_SIZE + 1)
            ),
            "dependencies.lock",
        )

    def test_lock_shape_version_target_and_package_fields_are_strict(self):
        cases = (
            (
                self._lock_data(lock_version=2),
                "UNSUPPORTED_DEPENDENCY_LOCK_VERSION",
            ),
            (
                self._lock_data(target={"python_abi": "cp311"}),
                "MISSING_DEPENDENCY_LOCK_FIELD",
            ),
            (
                self._lock_data(extra=True),
                "UNKNOWN_DEPENDENCY_LOCK_FIELD",
            ),
            (
                self._lock_data(packages=[{"name": "demo"}]),
                "MISSING_DEPENDENCY_LOCK_FIELD",
            ),
        )
        for value, code in cases:
            with self.subTest(code=code):
                self.assert_lock_error(
                    code,
                    lambda candidate=value: parse_dependency_lock(candidate),
                )

    def test_locked_names_and_wheel_paths_are_unique_and_safe(self):
        first = self._lock_data()["packages"][0]
        duplicate_name = dict(first, name="demo-package", wheel="other.whl")
        self.assert_lock_error(
            "DUPLICATE_LOCKED_PACKAGE",
            lambda: parse_dependency_lock(
                self._lock_data(packages=[first, duplicate_name])
            ),
        )

        duplicate_wheel = dict(first, name="other")
        self.assert_lock_error(
            "DUPLICATE_LOCKED_WHEEL",
            lambda: parse_dependency_lock(
                self._lock_data(packages=[first, duplicate_wheel])
            ),
        )

        for wheel in ("../demo.whl", "C:/demo.whl", "dependencies/demo.zip"):
            with self.subTest(wheel=wheel):
                invalid = dict(first, wheel=wheel)
                self.assert_lock_error(
                    "INVALID_LOCKED_WHEEL",
                    lambda package=invalid: parse_dependency_lock(
                        self._lock_data(packages=[package])
                    ),
                )

    def test_validation_binds_target_requirements_and_manifest_wheel_hashes(self):
        manifest = parse_manifest(self._manifest_data())
        dependency_lock = parse_dependency_lock(self._lock_data())
        self.assertIsNone(validate_dependency_lock(manifest, dependency_lock))
        self.assertEqual(
            parse_and_validate_dependency_lock(
                json.dumps(self._lock_data()), manifest
            ),
            dependency_lock,
        )

        wrong_target = parse_dependency_lock(
            self._lock_data(
                target={"python_abi": "cp312", "platform": "win_amd64"}
            )
        )
        self.assert_lock_error(
            "DEPENDENCY_LOCK_TARGET_MISMATCH",
            lambda: validate_dependency_lock(manifest, wrong_target),
            "target",
        )

        missing = parse_dependency_lock(self._lock_data(packages=[]))
        self.assert_lock_error(
            "LOCKED_DEPENDENCY_MISSING",
            lambda: validate_dependency_lock(manifest, missing),
            "packages",
        )

        incompatible_package = dict(
            self._lock_data()["packages"][0],
            version="3.0.0",
        )
        incompatible = parse_dependency_lock(
            self._lock_data(packages=[incompatible_package])
        )
        self.assert_lock_error(
            "LOCKED_DEPENDENCY_INCOMPATIBLE",
            lambda: validate_dependency_lock(manifest, incompatible),
            "packages",
        )

        unknown_wheel = dict(
            self._lock_data()["packages"][0],
            wheel="dependencies/wheels/other.whl",
        )
        self.assert_lock_error(
            "LOCKED_WHEEL_NOT_DECLARED",
            lambda: validate_dependency_lock(
                manifest,
                parse_dependency_lock(self._lock_data(packages=[unknown_wheel])),
            ),
        )

        wrong_hash = dict(
            self._lock_data()["packages"][0],
            sha256="f" * 64,
        )
        self.assert_lock_error(
            "LOCKED_WHEEL_HASH_MISMATCH",
            lambda: validate_dependency_lock(
                manifest,
                parse_dependency_lock(self._lock_data(packages=[wrong_hash])),
            ),
        )

    def test_dependency_policy_remains_reject_even_with_a_valid_lock(self):
        manifest = parse_manifest(self._manifest_data())
        self.assertIsNone(
            validate_dependency_lock(manifest, parse_dependency_lock(self._lock_data()))
        )

        from core.plugin_system.plugin_manifest import HostEnvironment

        host = HostEnvironment(
            app_version="1.0",
            api_version="1.0",
            python_abi="cp311",
            platform_tag="win_amd64",
            host_packages={},
        )
        self.assert_lock_error(
            "PYTHON_DEPENDENCY_UNSUPPORTED",
            lambda: check_compatibility(manifest, host),
            "dependencies.python",
        )
        self.assertIsNone(
            check_compatibility(
                manifest,
                host,
                python_dependency_policy=PythonDependencyPolicy.ALLOW_DECLARED,
            )
        )


class PluginDependencyLockIoTest(unittest.TestCase):
    def _package_files(self, wheel_root: Path, *, target_abi="cp311"):
        plugin_source = b"class Plugin: pass\n"
        wheel_source = WheelBuilder(wheel_root).write().read_bytes()
        wheel_path = "dependencies/wheels/demo_package-2.1.0-py3-none-any.whl"
        lock_data = {
            "lock_version": 1,
            "target": {
                "python_abi": target_abi,
                "platform": "win_amd64",
            },
            "packages": [
                {
                    "name": "demo-package",
                    "version": "2.1.0",
                    "wheel": wheel_path,
                    "sha256": hashlib.sha256(wheel_source).hexdigest(),
                }
            ],
        }
        lock_source = json.dumps(lock_data, sort_keys=True).encode("utf-8")
        file_contents = {
            "plugin.py": plugin_source,
            "dependencies/lock.json": lock_source,
            wheel_path: wheel_source,
        }
        manifest = {
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
            "dependencies": {
                "host": [],
                "python": ["demo-package>=2,<3"],
                "lock": "dependencies/lock.json",
            },
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {
                path: hashlib.sha256(content).hexdigest()
                for path, content in file_contents.items()
            },
            "requires_restart": True,
        }
        return manifest, file_contents

    def _write_directory(self, root: Path, manifest, file_contents):
        for relative_path, content in file_contents.items():
            path = root.joinpath(*relative_path.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (root / "manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )

    def test_package_and_directory_validate_declared_lock_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, file_contents = self._package_files(root)
            package = root / "sample.atplugin"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                for relative_path, content in file_contents.items():
                    archive.writestr(relative_path, content)

            info = inspect_plugin_package(package)
            staged = stage_plugin_package(package, root / "staging")
            installed = root / "installed"
            installed.mkdir()
            self._write_directory(installed, manifest, file_contents)

            self.assertEqual(info.normalized_manifest.dependencies.lock, "dependencies/lock.json")
            self.assertTrue(
                (staged.staging_path / "dependencies" / "wheels").is_dir()
            )
            self.assertIsNone(
                validate_plugin_directory(installed, parse_manifest(manifest))
            )

    def test_package_and_directory_reject_lock_target_mismatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest, file_contents = self._package_files(
                root,
                target_abi="cp312",
            )
            package = root / "sample.atplugin"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                for relative_path, content in file_contents.items():
                    archive.writestr(relative_path, content)

            with self.assertRaises(PluginPackageError) as package_error:
                inspect_plugin_package(package)
            self.assertEqual(
                package_error.exception.code,
                "DEPENDENCY_LOCK_TARGET_MISMATCH",
            )

            installed = root / "installed"
            installed.mkdir()
            self._write_directory(installed, manifest, file_contents)
            with self.assertRaises(PluginManifestError) as directory_error:
                validate_plugin_directory(installed, parse_manifest(manifest))
            self.assertEqual(
                directory_error.exception.code,
                "DEPENDENCY_LOCK_TARGET_MISMATCH",
            )


if __name__ == "__main__":
    unittest.main()
