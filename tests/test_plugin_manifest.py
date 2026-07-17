import unittest
from dataclasses import FrozenInstanceError

from packaging.version import Version

from core.plugin_system.plugin_manifest import (
    ApiVersion,
    HostEnvironment,
    PluginRequirement,
    PluginManifestError,
    PythonDependencyPolicy,
    check_compatibility,
    parse_manifest,
)


class PluginManifestContractTest(unittest.TestCase):
    def _v2(self, **overrides):
        manifest = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "description": "A test plugin",
            "version": "1.2.0",
            "entry": "src/plugin.py",
            "class": "SamplePlugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1.0.0,<2.0.0",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {
                "host": ["Paramiko>=5,<6"],
                "python": [],
            },
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {"src/plugin.py": "0" * 64},
            "permissions": ["ui"],
            "requires_restart": True,
        }
        manifest.update(overrides)
        return manifest

    @staticmethod
    def _host(**overrides):
        values = {
            "app_version": "1.5.0",
            "api_version": "1.0",
            "python_abi": "cp311",
            "platform_tag": "win_amd64",
            "host_packages": {"paramiko": "5.0.0"},
        }
        values.update(overrides)
        return HostEnvironment(**values)

    def assert_manifest_error(self, code, callback, field=None):
        with self.assertRaises(PluginManifestError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        if field is not None:
            self.assertEqual(caught.exception.field, field)

    def test_v1_parsing_preserves_legacy_dependency_semantics(self):
        source = {
            "id": "legacy_plugin",
            "name": "Legacy Plugin",
            "version": "1.0.0",
            "entry": "plugin.pyd",
            "class": "LegacyPlugin",
            "dependencies": ["sqlite3", "paramiko"],
            "permissions": ["ui"],
        }

        manifest = parse_manifest(source)

        self.assertEqual(manifest.manifest_version, 1)
        self.assertEqual(manifest.api_version, ApiVersion(1, 0))
        self.assertEqual(manifest.dependencies.legacy_imports, ("sqlite3", "paramiko"))
        self.assertEqual(manifest.dependencies.host, ())
        self.assertEqual(manifest.dependencies.python, ())
        self.assertTrue(manifest.requires_restart)
        self.assertEqual(manifest.entry, "plugin.pyd")
        check_compatibility(manifest, self._host())

    def test_v2_is_normalized_typed_and_deeply_immutable(self):
        source = self._v2(extensions={"sample": {"values": [1, 2]}})

        manifest = parse_manifest(source)
        source["extensions"]["sample"]["values"].append(3)

        self.assertEqual(manifest.version, Version("1.2.0"))
        self.assertEqual(manifest.api_version, ApiVersion(1, 0))
        self.assertEqual(manifest.plugin_id, "sample_plugin")
        self.assertEqual(manifest.id, "sample_plugin")
        self.assertEqual(manifest.entry, "src/plugin.py")
        self.assertEqual(manifest.dependencies.host[0].name, "paramiko")
        self.assertEqual(manifest.ui.type, "native")
        self.assertEqual(manifest.file_hashes["src/plugin.py"], "0" * 64)
        self.assertTrue(manifest.dependencies.host[0].accepts("5.0.0"))
        self.assertEqual(
            manifest.raw["extensions"]["sample"]["values"],
            (1, 2),
        )
        with self.assertRaises(FrozenInstanceError):
            manifest.name = "Changed"
        with self.assertRaises(TypeError):
            manifest.raw["name"] = "Changed"
        with self.assertRaises(TypeError):
            manifest.extensions["sample"] = {}

    def test_plugin_dependencies_are_optional_typed_and_deterministic(self):
        without_plugins = parse_manifest(self._v2())
        with_plugins = parse_manifest(
            self._v2(
                dependencies={
                    "host": ["Paramiko>=5,<6"],
                    "python": [],
                    "plugins": {
                        "zeta_plugin": ">=2,<3",
                        "alpha.plugin": "~=1.4",
                    },
                }
            )
        )

        self.assertEqual(without_plugins.dependencies.plugins, ())
        self.assertEqual(
            with_plugins.dependencies.plugins,
            (
                PluginRequirement("alpha.plugin", "~=1.4"),
                PluginRequirement("zeta_plugin", "<3,>=2"),
            ),
        )
        self.assertTrue(with_plugins.dependencies.plugins[0].accepts("1.4.5"))
        self.assertFalse(with_plugins.dependencies.plugins[0].accepts("2.0"))
        with self.assertRaises(FrozenInstanceError):
            with_plugins.dependencies.plugins[0].specifier = ">=0"

    def test_plugin_dependency_schema_uses_stable_errors(self):
        cases = (
            ([], "INVALID_PLUGIN_DEPENDENCIES", "dependencies.plugins"),
            (
                {"BadPlugin": ">=1"},
                "INVALID_PLUGIN_DEPENDENCY_ID",
                "dependencies.plugins.BadPlugin",
            ),
            (
                {"other_plugin": ""},
                "INVALID_PLUGIN_DEPENDENCY_SPECIFIER",
                "dependencies.plugins.other_plugin",
            ),
            (
                {"other_plugin": "not a specifier"},
                "INVALID_PLUGIN_DEPENDENCY_SPECIFIER",
                "dependencies.plugins.other_plugin",
            ),
            (
                {"sample_plugin": ">=1"},
                "SELF_PLUGIN_DEPENDENCY",
                "dependencies.plugins.sample_plugin",
            ),
        )
        for plugins, code, field in cases:
            with self.subTest(code=code):
                self.assert_manifest_error(
                    code,
                    lambda value=plugins: parse_manifest(
                        self._v2(
                            dependencies={
                                "host": ["Paramiko>=5,<6"],
                                "python": [],
                                "plugins": value,
                            }
                        )
                    ),
                    field,
                )

    def test_manifest_version_and_v2_shape_use_stable_errors(self):
        cases = (
            ({"manifest_version": 3}, "UNSUPPORTED_MANIFEST_VERSION", "manifest_version"),
            (
                self._v2(manifest_version="2"),
                "INVALID_MANIFEST_VERSION",
                "manifest_version",
            ),
            (
                {key: value for key, value in self._v2().items() if key != "api_version"},
                "MISSING_MANIFEST_FIELD",
                "api_version",
            ),
            (
                self._v2(unknown_field=True),
                "UNKNOWN_MANIFEST_FIELD",
                "unknown_field",
            ),
        )
        for manifest, code, field in cases:
            with self.subTest(code=code):
                self.assert_manifest_error(
                    code,
                    lambda value=manifest: parse_manifest(value),
                    field,
                )

    def test_v2_requires_safe_python_bootstrap_and_valid_core_fields(self):
        cases = (
            (self._v2(id="BadPlugin"), "INVALID_PLUGIN_ID", "id"),
            (self._v2(version="not-a-version"), "INVALID_PLUGIN_VERSION", "version"),
            (self._v2(entry="../plugin.py"), "INVALID_ENTRY", "entry"),
            (self._v2(entry="plugin.cp311-win_amd64.pyd"), "INVALID_ENTRY", "entry"),
            (self._v2(**{"class": "Not.Valid"}), "INVALID_PLUGIN_CLASS", "class"),
            (self._v2(api_version="1"), "INVALID_API_VERSION", "api_version"),
            (
                self._v2(requires_restart="yes"),
                "INVALID_MANIFEST_FIELD",
                "requires_restart",
            ),
        )
        for manifest, code, field in cases:
            with self.subTest(field=field, code=code):
                self.assert_manifest_error(
                    code,
                    lambda value=manifest: parse_manifest(value),
                    field,
                )

    def test_v2_compatibility_structure_is_strict(self):
        cases = (
            (
                {"app": ">=1", "python_abi": "cp311"},
                "MISSING_MANIFEST_FIELD",
                "compatibility.platform",
            ),
            (
                {
                    "app": ">=1",
                    "python_abi": "cp311",
                    "platform": "win_amd64",
                    "architecture": "amd64",
                },
                "UNKNOWN_MANIFEST_FIELD",
                "compatibility.architecture",
            ),
            (
                {"app": "not valid", "python_abi": "cp311", "platform": "win_amd64"},
                "INVALID_APP_SPECIFIER",
                "compatibility.app",
            ),
            (
                {"app": ">=1", "python_abi": "cpython-311", "platform": "win_amd64"},
                "INVALID_PYTHON_ABI",
                "compatibility.python_abi",
            ),
            (
                {"app": ">=1", "python_abi": "cp311", "platform": "windows"},
                "INVALID_PLATFORM_TAG",
                "compatibility.platform",
            ),
        )
        for compatibility, code, field in cases:
            with self.subTest(code=code):
                self.assert_manifest_error(
                    code,
                    lambda value=compatibility: parse_manifest(
                        self._v2(compatibility=value)
                    ),
                    field,
                )

    def test_v2_dependency_requirements_are_deterministic(self):
        cases = (
            (["paramiko"], "DEPENDENCY_VERSION_REQUIRED"),
            (["demo @ https://example.invalid/demo.whl"], "DEPENDENCY_URL_NOT_ALLOWED"),
            (["demo>=1; python_version >= '3.11'"], "DEPENDENCY_MARKER_NOT_ALLOWED"),
            (["demo[fast]>=1"], "DEPENDENCY_EXTRAS_NOT_ALLOWED"),
            (["Demo>=1", "demo<2"], "DUPLICATE_DEPENDENCY"),
        )
        for requirements, code in cases:
            with self.subTest(code=code):
                dependencies = {"host": requirements, "python": []}
                self.assert_manifest_error(
                    code,
                    lambda value=dependencies: parse_manifest(
                        self._v2(dependencies=value)
                    ),
                    "dependencies.host",
                )

        cross_group = {
            "host": ["Demo>=1"],
            "python": ["demo<2"],
        }
        self.assert_manifest_error(
            "DUPLICATE_DEPENDENCY",
            lambda: parse_manifest(self._v2(dependencies=cross_group)),
            "dependencies",
        )

    def test_v2_ui_native_modules_and_file_hashes_are_explicit(self):
        native_hash = "a" * 64
        manifest = parse_manifest(
            self._v2(
                ui={"type": "web", "entry": "dist/index.html"},
                native_modules=[
                    {
                        "module": "sample.fast",
                        "path": "sample/fast.cp311-win_amd64.pyd",
                        "sha256": native_hash,
                    }
                ],
                files={
                    "src/plugin.py": "0" * 64,
                    "dist/index.html": "1" * 64,
                    "sample/fast.cp311-win_amd64.pyd": native_hash,
                },
            )
        )

        self.assertEqual(manifest.ui.entry, "dist/index.html")
        self.assertEqual(manifest.native_modules[0].module, "sample.fast")
        self.assertEqual(manifest.native_modules[0].sha256, native_hash)

    def test_v2_rejects_unsafe_or_incomplete_file_declarations(self):
        cases = (
            (
                {"ui": {"type": "web", "entry": "dist/app.js"}},
                "INVALID_UI",
            ),
            (
                {"files": {"manifest.json": "0" * 64}},
                "INVALID_FILE_HASHES",
            ),
            (
                {"files": {"other.py": "0" * 64}},
                "MISSING_FILE_HASH",
            ),
            (
                {
                    "native_modules": [
                        {
                            "module": "sample.fast",
                            "path": "sample/wrong.cp311-win_amd64.pyd",
                            "sha256": "a" * 64,
                        }
                    ],
                    "files": {
                        "src/plugin.py": "0" * 64,
                        "sample/wrong.cp311-win_amd64.pyd": "a" * 64,
                    },
                },
                "NATIVE_MODULE_NAME_MISMATCH",
            ),
            (
                {
                    "native_modules": [
                        {
                            "module": "sample.fast",
                            "path": "sample/fast.cp311-win_amd64.pyd",
                            "sha256": "a" * 64,
                        }
                    ],
                    "files": {
                        "src/plugin.py": "0" * 64,
                        "sample/fast.cp311-win_amd64.pyd": "b" * 64,
                    },
                },
                "NATIVE_MODULE_HASH_MISMATCH",
            ),
            (
                {
                    "native_modules": [
                        {
                            "module": "sample.fast",
                            "path": "sample/fast.cp311-win_amd64.pyd",
                            "sha256": "a" * 64,
                        }
                    ],
                    "files": {
                        "src/plugin.py": "0" * 64,
                        "sample/fast.cp311-win_amd64.pyd": "a" * 64,
                    },
                    "requires_restart": False,
                },
                "NATIVE_RESTART_REQUIRED",
            ),
        )
        for overrides, code in cases:
            with self.subTest(code=code):
                self.assert_manifest_error(
                    code,
                    lambda values=overrides: parse_manifest(self._v2(**values)),
                )

    def test_compatible_v2_manifest_passes_all_host_checks(self):
        manifest = parse_manifest(self._v2())

        self.assertIsNone(check_compatibility(manifest, self._host()))
        self.assertIsNone(
            check_compatibility(
                manifest,
                self._host(api_version="1.2"),
            )
        )

    def test_app_api_abi_and_platform_mismatches_are_distinct(self):
        cases = (
            (
                self._host(app_version="2.0.0"),
                "INCOMPATIBLE_APP_VERSION",
                "compatibility.app",
            ),
            (
                self._host(api_version="0.9"),
                "INCOMPATIBLE_API_VERSION",
                "api_version",
            ),
            (
                self._host(python_abi="cp312"),
                "INCOMPATIBLE_PYTHON_ABI",
                "compatibility.python_abi",
            ),
            (
                self._host(platform_tag="win_arm64"),
                "INCOMPATIBLE_PLATFORM",
                "compatibility.platform",
            ),
        )
        manifest = parse_manifest(self._v2())
        for host, code, field in cases:
            with self.subTest(code=code):
                self.assert_manifest_error(
                    code,
                    lambda value=host: check_compatibility(manifest, value),
                    field,
                )

    def test_host_dependency_missing_and_version_mismatch_are_distinct(self):
        manifest = parse_manifest(self._v2())

        self.assert_manifest_error(
            "HOST_DEPENDENCY_MISSING",
            lambda: check_compatibility(
                manifest,
                self._host(host_packages={}),
            ),
            "dependencies.host",
        )
        self.assert_manifest_error(
            "HOST_DEPENDENCY_INCOMPATIBLE",
            lambda: check_compatibility(
                manifest,
                self._host(host_packages={"paramiko": "4.0.0"}),
            ),
            "dependencies.host",
        )

    def test_python_dependencies_are_explicitly_gated_and_cannot_shadow_host(self):
        dependency_manifest = parse_manifest(
            self._v2(
                dependencies={
                    "host": ["Paramiko>=5,<6"],
                    "python": ["orjson==3.10.0"],
                    "lock": "dependencies/lock.json",
                },
                files={
                    "src/plugin.py": "0" * 64,
                    "dependencies/lock.json": "1" * 64,
                },
            )
        )
        self.assert_manifest_error(
            "PYTHON_DEPENDENCY_UNSUPPORTED",
            lambda: check_compatibility(dependency_manifest, self._host()),
            "dependencies.python",
        )
        self.assertIsNone(
            check_compatibility(
                dependency_manifest,
                self._host(),
                python_dependency_policy=PythonDependencyPolicy.ALLOW_DECLARED,
            )
        )

        shadowing_manifest = parse_manifest(
            self._v2(
                dependencies={
                    "host": [],
                    "python": ["Paramiko==5.0.0"],
                    "lock": "dependencies/lock.json",
                },
                files={
                    "src/plugin.py": "0" * 64,
                    "dependencies/lock.json": "1" * 64,
                },
            )
        )
        self.assert_manifest_error(
            "PYTHON_DEPENDENCY_SHADOWS_HOST",
            lambda: check_compatibility(
                shadowing_manifest,
                self._host(),
                python_dependency_policy=PythonDependencyPolicy.ALLOW_DECLARED,
            ),
            "dependencies.python",
        )

    def test_host_environment_is_normalized_immutable_and_validated(self):
        packages = {"PySide6-Fluent-Widgets": "1.11.0"}
        imports = {"PySide6"}
        dlls = {"Qt6Core.DLL"}
        host = self._host(
            python_abi="CP311",
            platform_tag="WIN_AMD64",
            host_packages=packages,
            host_imports=imports,
            host_dll_basenames=dlls,
        )
        packages["other"] = "1.0"
        imports.add("other")
        dlls.add("other.dll")

        self.assertEqual(host.app_version, Version("1.5.0"))
        self.assertEqual(host.api_version, ApiVersion(1, 0))
        self.assertEqual(host.python_abi, "cp311")
        self.assertEqual(host.platform_tag, "win_amd64")
        self.assertEqual(
            host.host_packages["pyside6-fluent-widgets"],
            Version("1.11.0"),
        )
        self.assertNotIn("other", host.host_packages)
        self.assertEqual(host.host_imports, frozenset({"pyside6"}))
        self.assertEqual(host.host_dll_basenames, frozenset({"qt6core.dll"}))
        with self.assertRaises(TypeError):
            host.host_packages["other"] = Version("1.0")

        self.assert_manifest_error(
            "INVALID_HOST_ENVIRONMENT",
            lambda: self._host(python_abi="python311"),
            "python_abi",
        )
        self.assert_manifest_error(
            "INVALID_HOST_ENVIRONMENT",
            lambda: self._host(host_packages={"Paramiko": "5", "paramiko": "5"}),
            "host_packages",
        )
        self.assert_manifest_error(
            "INVALID_HOST_ENVIRONMENT",
            lambda: self._host(host_imports={"bad-name"}),
            "host_imports",
        )
        self.assert_manifest_error(
            "INVALID_HOST_ENVIRONMENT",
            lambda: self._host(host_dll_basenames={"bin/qt6core.dll"}),
            "host_dll_basenames",
        )


if __name__ == "__main__":
    unittest.main()
