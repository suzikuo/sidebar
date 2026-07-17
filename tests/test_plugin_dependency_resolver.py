import unittest
from pathlib import Path

from packaging.tags import Tag
from packaging.version import Version

from core.plugin_system.plugin_dependency_lock import parse_dependency_lock
from core.plugin_system.plugin_dependency_resolver import (
    PluginDependencyInput,
    PluginDependencyResolutionError,
    resolve_dependency_set,
)
from core.plugin_system.plugin_wheel import WheelArtifact


def _artifact(
    name,
    version,
    digest,
    *,
    requirements=(),
    installed_files=(),
    top_level_imports=(),
    dlls=(),
):
    return WheelArtifact(
        path=Path(f"{name}-{version}.whl"),
        sha256=digest,
        distribution=name,
        version=Version(version),
        build_tag=(),
        tags=frozenset({Tag("py3", "none", "any")}),
        root_is_purelib=not dlls,
        requires_python=None,
        requirements=tuple(requirements),
        files=tuple(installed_files),
        installed_files=tuple(installed_files),
        top_level_imports=tuple(top_level_imports),
        native_extensions=(),
        dlls=tuple(dlls),
        target_python_abi="cp311",
        target_platform="win_amd64",
    )


def _lock(*packages, python_abi="cp311", platform="win_amd64"):
    return parse_dependency_lock(
        {
            "lock_version": 1,
            "target": {
                "python_abi": python_abi,
                "platform": platform,
            },
            "packages": [
                {
                    "name": name,
                    "version": version,
                    "wheel": f"dependencies/{name}-{version}.whl",
                    "sha256": digest,
                }
                for name, version, digest in packages
            ],
        }
    )


def _input(lock, *artifacts):
    return PluginDependencyInput(lock=lock, wheels=tuple(artifacts))


class PluginDependencyResolverTest(unittest.TestCase):
    SHA_A = "a" * 64
    SHA_B = "b" * 64
    SHA_C = "c" * 64

    def assert_resolution_error(self, code, callback):
        with self.assertRaises(PluginDependencyResolutionError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def test_identical_wheel_is_shared_with_deterministic_owners(self):
        artifact = _artifact(
            "demo",
            "1.0",
            self.SHA_A,
            installed_files=("demo/__init__.py",),
            top_level_imports=("demo",),
        )
        dependency_lock = _lock(("demo", "1.0", self.SHA_A))

        resolved = resolve_dependency_set(
            {
                "plugin-b": _input(dependency_lock, artifact),
                "plugin-a": _input(dependency_lock, artifact),
            }
        )

        self.assertEqual(len(resolved.packages), 1)
        self.assertEqual(resolved.packages[0].owners, ("plugin-a", "plugin-b"))
        self.assertEqual(resolved.plugin_packages["plugin-a"], ("demo",))
        with self.assertRaises(TypeError):
            resolved.plugin_packages["plugin-c"] = ()

    def test_version_and_same_version_hash_conflicts_are_distinct(self):
        first = _artifact("demo", "1.0", self.SHA_A)
        second_version = _artifact("demo", "2.0", self.SHA_B)
        second_hash = _artifact("demo", "1.0", self.SHA_B)

        self.assert_resolution_error(
            "DEPENDENCY_VERSION_CONFLICT",
            lambda: resolve_dependency_set(
                {
                    "one": _input(_lock(("demo", "1.0", self.SHA_A)), first),
                    "two": _input(
                        _lock(("demo", "2.0", self.SHA_B)),
                        second_version,
                    ),
                }
            ),
        )
        self.assert_resolution_error(
            "DEPENDENCY_ARTIFACT_CONFLICT",
            lambda: resolve_dependency_set(
                {
                    "one": _input(_lock(("demo", "1.0", self.SHA_A)), first),
                    "two": _input(
                        _lock(("demo", "1.0", self.SHA_B)),
                        second_hash,
                    ),
                }
            ),
        )

    def test_transitive_closure_and_marker_versions_are_checked(self):
        main = _artifact(
            "main",
            "1.0",
            self.SHA_A,
            requirements=("dep>=2", "ignored; python_version < '3'"),
        )
        missing_lock = _lock(("main", "1.0", self.SHA_A))
        self.assert_resolution_error(
            "DEPENDENCY_CLOSURE_INCOMPLETE",
            lambda: resolve_dependency_set(
                {"plugin": _input(missing_lock, main)}
            ),
        )

        old_dep = _artifact("dep", "1.0", self.SHA_B)
        old_lock = _lock(
            ("main", "1.0", self.SHA_A),
            ("dep", "1.0", self.SHA_B),
        )
        self.assert_resolution_error(
            "DEPENDENCY_CLOSURE_VERSION_MISMATCH",
            lambda: resolve_dependency_set(
                {"plugin": _input(old_lock, main, old_dep)}
            ),
        )

        current_dep = _artifact("dep", "2.1", self.SHA_C)
        current_lock = _lock(
            ("main", "1.0", self.SHA_A),
            ("dep", "2.1", self.SHA_C),
        )
        self.assertEqual(
            len(
                resolve_dependency_set(
                    {"plugin": _input(current_lock, main, current_dep)}
                ).packages
            ),
            2,
        )

        host_main = _artifact(
            "host-main",
            "1.0",
            self.SHA_A,
            requirements=("packaging>=25",),
        )
        host_lock = _lock(("host-main", "1.0", self.SHA_A))
        self.assertEqual(
            len(
                resolve_dependency_set(
                    {"plugin": _input(host_lock, host_main)},
                    host_packages={"packaging": "26.0"},
                ).packages
            ),
            1,
        )

    def test_host_and_standard_library_shadowing_are_rejected(self):
        host_artifact = _artifact("packaging", "26.0", self.SHA_A)
        self.assert_resolution_error(
            "DEPENDENCY_SHADOWS_HOST",
            lambda: resolve_dependency_set(
                {
                    "plugin": _input(
                        _lock(("packaging", "26.0", self.SHA_A)),
                        host_artifact,
                    )
                },
                host_packages={"packaging": "26.0"},
            ),
        )

        stdlib_artifact = _artifact(
            "shadow",
            "1.0",
            self.SHA_B,
            installed_files=("json.py",),
            top_level_imports=("json",),
        )
        self.assert_resolution_error(
            "DEPENDENCY_SHADOWS_STDLIB",
            lambda: resolve_dependency_set(
                {
                    "plugin": _input(
                        _lock(("shadow", "1.0", self.SHA_B)),
                        stdlib_artifact,
                    )
                }
            ),
        )

    def test_differently_named_distribution_cannot_shadow_host_import(self):
        artifact = _artifact(
            "not-pyside",
            "1.0",
            self.SHA_A,
            installed_files=("PySide6/__init__.py",),
            top_level_imports=("PySide6",),
        )

        self.assert_resolution_error(
            "DEPENDENCY_SHADOWS_HOST_IMPORT",
            lambda: resolve_dependency_set(
                {
                    "plugin": _input(
                        _lock(("not-pyside", "1.0", self.SHA_A)),
                        artifact,
                    )
                },
                host_imports={"pYsIdE6"},
            ),
        )

    def test_differently_named_distribution_cannot_shadow_host_dll(self):
        artifact = _artifact(
            "native-helper",
            "1.0",
            self.SHA_A,
            installed_files=("native/PYTHON311.DLL",),
            dlls=("native/PYTHON311.DLL",),
        )

        self.assert_resolution_error(
            "DEPENDENCY_SHADOWS_HOST_DLL",
            lambda: resolve_dependency_set(
                {
                    "plugin": _input(
                        _lock(("native-helper", "1.0", self.SHA_A)),
                        artifact,
                    )
                },
                host_dll_basenames={"Python311.dll"},
            ),
        )

    def test_host_import_and_dll_inputs_are_strictly_validated(self):
        invalid_imports = (
            "PySide6",
            ["nested.module"],
            [" leading"],
            ["class"],
            [1],
        )
        for imports in invalid_imports:
            with self.subTest(host_imports=imports):
                self.assert_resolution_error(
                    "INVALID_HOST_IMPORT",
                    lambda imports=imports: resolve_dependency_set(
                        {},
                        host_imports=imports,
                    ),
                )

        invalid_dlls = (
            "python311.dll",
            ["bin/python311.dll"],
            ["python311.pyd"],
            [" trailing.dll "],
            [1],
        )
        for dlls in invalid_dlls:
            with self.subTest(host_dll_basenames=dlls):
                self.assert_resolution_error(
                    "INVALID_HOST_DLL",
                    lambda dlls=dlls: resolve_dependency_set(
                        {},
                        host_dll_basenames=dlls,
                    ),
                )

        for packages in ([], {"Paramiko": "5", "paramiko": "5"}):
            with self.subTest(host_packages=packages):
                self.assert_resolution_error(
                    "INVALID_HOST_DEPENDENCY",
                    lambda packages=packages: resolve_dependency_set(
                        {},
                        host_packages=packages,
                    ),
                )

    def test_normalized_host_inventory_preserves_existing_resolution(self):
        artifact = _artifact(
            "demo",
            "1.0",
            self.SHA_A,
            installed_files=("demo/__init__.py", "demo/helper.dll"),
            top_level_imports=("demo",),
            dlls=("demo/helper.dll",),
        )
        resolved = resolve_dependency_set(
            {
                "plugin": _input(
                    _lock(("demo", "1.0", self.SHA_A)),
                    artifact,
                )
            },
            host_imports=(name for name in ("PySide6", "pyside6")),
            host_dll_basenames=("python311.dll", "PYTHON311.DLL"),
        )

        self.assertEqual(tuple(item.name for item in resolved.packages), ("demo",))

    def test_file_import_and_dll_conflicts_are_distinct(self):
        def resolve_pair(first, second):
            dependency_lock = _lock(
                (first.distribution, str(first.version), first.sha256),
                (second.distribution, str(second.version), second.sha256),
            )
            return resolve_dependency_set(
                {"plugin": _input(dependency_lock, first, second)}
            )

        self.assert_resolution_error(
            "DEPENDENCY_FILE_CONFLICT",
            lambda: resolve_pair(
                _artifact(
                    "one",
                    "1.0",
                    self.SHA_A,
                    installed_files=("shared/data.txt",),
                ),
                _artifact(
                    "two",
                    "1.0",
                    self.SHA_B,
                    installed_files=("shared/data.txt",),
                ),
            ),
        )
        self.assert_resolution_error(
            "DEPENDENCY_IMPORT_CONFLICT",
            lambda: resolve_pair(
                _artifact(
                    "one",
                    "1.0",
                    self.SHA_A,
                    installed_files=("one.py",),
                    top_level_imports=("shared",),
                ),
                _artifact(
                    "two",
                    "1.0",
                    self.SHA_B,
                    installed_files=("two.py",),
                    top_level_imports=("shared",),
                ),
            ),
        )
        self.assert_resolution_error(
            "DEPENDENCY_DLL_CONFLICT",
            lambda: resolve_pair(
                _artifact(
                    "one",
                    "1.0",
                    self.SHA_A,
                    installed_files=("one/helper.dll",),
                    dlls=("one/helper.dll",),
                ),
                _artifact(
                    "two",
                    "1.0",
                    self.SHA_B,
                    installed_files=("two/helper.dll",),
                    dlls=("two/helper.dll",),
                ),
            ),
        )

        duplicate_dll = _artifact(
            "one",
            "1.0",
            self.SHA_A,
            installed_files=("one/helper.dll", "one/libs/helper.dll"),
            dlls=("one/helper.dll", "one/libs/helper.dll"),
        )
        self.assert_resolution_error(
            "DEPENDENCY_DLL_CONFLICT",
            lambda: resolve_pair(
                duplicate_dll,
                _artifact("two", "1.0", self.SHA_B),
            ),
        )

    def test_dependency_targets_must_match(self):
        first = _artifact("one", "1.0", self.SHA_A)
        second = _artifact("two", "1.0", self.SHA_B)
        self.assert_resolution_error(
            "DEPENDENCY_TARGET_CONFLICT",
            lambda: resolve_dependency_set(
                {
                    "one": _input(
                        _lock(("one", "1.0", self.SHA_A)),
                        first,
                    ),
                    "two": _input(
                        _lock(
                            ("two", "1.0", self.SHA_B),
                            python_abi="cp312",
                        ),
                        second,
                    ),
                }
            ),
        )
        self.assert_resolution_error(
            "LOCKED_WHEEL_TARGET_MISMATCH",
            lambda: resolve_dependency_set(
                {
                    "one": _input(
                        _lock(
                            ("one", "1.0", self.SHA_A),
                            python_abi="cp312",
                        ),
                        first,
                    )
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
