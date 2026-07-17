import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from packaging.version import Version

from core.plugin_system.host_runtime_lock import (
    MAX_HOST_RUNTIME_LOCK_SIZE,
    HostRuntimeLock,
    HostRuntimeLockError,
    build_host_runtime_lock,
    generate_host_runtime_lock,
    load_host_runtime_lock,
    parse_host_runtime_lock,
    parse_host_runtime_lock_json,
    serialize_host_runtime_lock,
    validate_host_runtime_lock,
)


def package(distribution="aiohttp", version="3.14.1", imports=None):
    return {
        "distribution": distribution,
        "version": version,
        "top_level_imports": [distribution.replace("-", "_")]
        if imports is None
        else imports,
    }


def dll(path="python311.dll", sha256=None, size=5_000_000):
    return {"path": path, "sha256": sha256 or "a" * 64, "size": size}


def lock_data(**changes):
    data = {
        "lock_version": 1,
        "app_version": "1.0.0",
        "target": {"python_abi": "cp311", "platform": "win_amd64"},
        "packages": [package()],
        "dlls": [dll()],
    }
    data.update(changes)
    return data


class HostRuntimeLockTest(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(HostRuntimeLockError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def test_explicit_builder_sorts_and_serializes_deterministically(self):
        facts = [
            package("paramiko", "5.0.0", ["paramiko"]),
            package("aiohttp", "3.14.1", ["multidict", "aiohttp"]),
        ]
        with mock.patch(
            "importlib.metadata.version",
            side_effect=AssertionError("environment metadata must not be scanned"),
        ):
            first = generate_host_runtime_lock(
                app_version="1.0.0",
                python_abi="cp311",
                platform="win_amd64",
                packages=facts,
                dlls=[dll("qt6core.dll", "b" * 64), dll()],
            )
            second = generate_host_runtime_lock(
                app_version="1.0.0",
                python_abi="cp311",
                platform="win_amd64",
                packages=reversed(facts),
                dlls=[dll(), dll("qt6core.dll", "b" * 64)],
            )

        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        raw = json.loads(first)
        self.assertEqual(
            [item["distribution"] for item in raw["packages"]],
            ["aiohttp", "paramiko"],
        )
        self.assertEqual(
            raw["packages"][0]["top_level_imports"], ["aiohttp", "multidict"]
        )
        self.assertEqual(
            [item["path"] for item in raw["dlls"]],
            ["python311.dll", "qt6core.dll"],
        )
        self.assertEqual(
            first,
            serialize_host_runtime_lock(parse_host_runtime_lock_json(first)),
        )

    def test_dtos_and_derived_maps_are_immutable(self):
        runtime_lock = parse_host_runtime_lock(lock_data())
        self.assertIsInstance(runtime_lock.packages, tuple)
        self.assertIsInstance(runtime_lock.packages[0].top_level_imports, tuple)
        self.assertEqual(str(runtime_lock.package_versions["aiohttp"]), "3.14.1")
        self.assertEqual(runtime_lock.import_owners["aiohttp"], ("aiohttp",))
        self.assertEqual(runtime_lock.protected_imports, frozenset({"aiohttp"}))
        self.assertEqual(
            runtime_lock.protected_dll_basenames,
            frozenset({"python311.dll"}),
        )
        with self.assertRaises(FrozenInstanceError):
            runtime_lock.lock_version = 2
        with self.assertRaises(TypeError):
            runtime_lock.package_versions["aiohttp"] = "0"

    def test_import_owner_map_uses_casefolded_lookup_keys(self):
        data = lock_data(packages=[package("pyside6", "6.10.2", ["PySide6"])])
        runtime_lock = parse_host_runtime_lock(data)
        self.assertEqual(runtime_lock.import_owners["pyside6"], ("pyside6",))
        self.assertNotIn("PySide6", runtime_lock.import_owners)

    def test_load_reads_shipped_lock_and_validates_target_without_metadata(self):
        payload = generate_host_runtime_lock(
            app_version="1.0.0",
            python_abi="cp311",
            platform="win_amd64",
            packages=[package()],
            dlls=[dll()],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "HOST_RUNTIME_LOCK.json"
            path.write_bytes(payload)
            with mock.patch(
                "importlib.metadata.version",
                side_effect=AssertionError("runtime metadata fallback is forbidden"),
            ):
                runtime_lock = load_host_runtime_lock(
                    path,
                    expected_app_version="1.0.0",
                    expected_python_abi="cp311",
                    expected_platform="win_amd64",
                )
        self.assertEqual(runtime_lock.target.platform, "win_amd64")

    def test_duplicate_json_keys_are_rejected_at_any_depth(self):
        payload = (
            '{"lock_version":1,"app_version":"1.0.0",'
            '"target":{"python_abi":"cp311","python_abi":"cp312",'
            '"platform":"win_amd64"},"packages":[]}'
        )
        self.assert_code(
            "DUPLICATE_HOST_RUNTIME_LOCK_KEY",
            lambda: parse_host_runtime_lock_json(payload),
        )

    def test_missing_and_unknown_fields_are_rejected_at_each_schema_level(self):
        missing_root = lock_data()
        missing_root.pop("packages")
        unknown_target = lock_data()
        unknown_target["target"] = {**unknown_target["target"], "abi3": False}
        missing_package = lock_data()
        missing_package["packages"] = [{"distribution": "aiohttp", "version": "3.14.1"}]
        unknown_package = lock_data()
        unknown_package["packages"] = [{**package(), "wheel": "aiohttp.whl"}]
        for data, code in (
            (missing_root, "MISSING_HOST_RUNTIME_LOCK_FIELD"),
            (unknown_target, "UNKNOWN_HOST_RUNTIME_LOCK_FIELD"),
            (missing_package, "MISSING_HOST_RUNTIME_LOCK_FIELD"),
            (unknown_package, "UNKNOWN_HOST_RUNTIME_LOCK_FIELD"),
        ):
            with self.subTest(code=code, data=data):
                self.assert_code(code, lambda data=data: parse_host_runtime_lock(data))

    def test_lock_version_requires_exact_integer_one(self):
        for value in (True, 1.0, "1", 2, None):
            with self.subTest(value=value):
                self.assert_code(
                    "UNSUPPORTED_HOST_RUNTIME_LOCK_VERSION",
                    lambda value=value: parse_host_runtime_lock(
                        lock_data(lock_version=value)
                    ),
                )

    def test_app_and_package_versions_must_be_exact_canonical_versions(self):
        for value in ("", "latest", " 1.0.0", "1.0.0+ABC"):
            with self.subTest(kind="app", value=value):
                self.assert_code(
                    "INVALID_HOST_RUNTIME_VERSION",
                    lambda value=value: parse_host_runtime_lock(
                        lock_data(app_version=value)
                    ),
                )
            data = lock_data()
            data["packages"][0]["version"] = value
            with self.subTest(kind="package", value=value):
                self.assert_code(
                    "INVALID_HOST_RUNTIME_VERSION",
                    lambda data=data: parse_host_runtime_lock(data),
                )

    def test_target_values_must_be_canonical(self):
        for key, value in (
            ("python_abi", "CP311"),
            ("python_abi", "py3"),
            ("platform", "WIN_AMD64"),
            ("platform", "win-amd64"),
            ("platform", " win_amd64"),
            ("platform", []),
        ):
            data = lock_data()
            data["target"][key] = value
            with self.subTest(key=key, value=value):
                self.assert_code(
                    "INVALID_HOST_RUNTIME_TARGET",
                    lambda data=data: parse_host_runtime_lock(data),
                )

    def test_distribution_names_must_be_canonical_and_unique(self):
        for name in ("PySide6", "zope.interface", "bad name", ""):
            data = lock_data(packages=[package(name, imports=["owner"])])
            with self.subTest(name=name):
                self.assert_code(
                    "INVALID_HOST_RUNTIME_DISTRIBUTION",
                    lambda data=data: parse_host_runtime_lock(data),
                )
        duplicate = lock_data(packages=[package(), package(imports=[])])
        self.assert_code(
            "DUPLICATE_HOST_RUNTIME_PACKAGE",
            lambda: parse_host_runtime_lock(duplicate),
        )

    def test_parsed_packages_and_imports_must_already_be_sorted(self):
        unsorted_packages = lock_data(
            packages=[package("paramiko", "5.0.0"), package()]
        )
        self.assert_code(
            "NONCANONICAL_HOST_RUNTIME_PACKAGES",
            lambda: parse_host_runtime_lock(unsorted_packages),
        )
        unsorted_imports = lock_data(
            packages=[package(imports=["multidict", "aiohttp"])]
        )
        self.assert_code(
            "NONCANONICAL_HOST_RUNTIME_IMPORTS",
            lambda: parse_host_runtime_lock(unsorted_imports),
        )

    def test_empty_runtime_facts_are_rejected(self):
        self.assert_code(
            "EMPTY_HOST_RUNTIME_PACKAGES",
            lambda: parse_host_runtime_lock(lock_data(packages=[])),
        )
        self.assert_code(
            "EMPTY_HOST_RUNTIME_IMPORT_OWNERS",
            lambda: parse_host_runtime_lock(
                lock_data(packages=[package(imports=[])])
            ),
        )
        self.assert_code(
            "EMPTY_HOST_RUNTIME_DLLS",
            lambda: parse_host_runtime_lock(lock_data(dlls=[])),
        )

    def test_dll_inventory_shape_and_values_are_strict(self):
        cases = (
            ([{"path": "python311.dll", "size": 1}], "MISSING_HOST_RUNTIME_LOCK_FIELD"),
            ([{**dll(), "name": "python311.dll"}], "UNKNOWN_HOST_RUNTIME_LOCK_FIELD"),
            ([dll("../python311.dll")], "INVALID_HOST_RUNTIME_DLL_PATH"),
            ([dll("C:/python311.dll")], "INVALID_HOST_RUNTIME_DLL_PATH"),
            ([dll("bin\\python311.dll")], "INVALID_HOST_RUNTIME_DLL_PATH"),
            ([dll("bin/python:311.dll")], "INVALID_HOST_RUNTIME_DLL_PATH"),
            ([dll("python311.pyd")], "INVALID_HOST_RUNTIME_DLL_PATH"),
            ([dll(sha256="A" * 64)], "INVALID_HOST_RUNTIME_DLL_DIGEST"),
            ([dll(sha256="a" * 63)], "INVALID_HOST_RUNTIME_DLL_DIGEST"),
            ([dll(size=True)], "INVALID_HOST_RUNTIME_DLL_SIZE"),
            ([dll(size=1.0)], "INVALID_HOST_RUNTIME_DLL_SIZE"),
            ([dll(size=0)], "INVALID_HOST_RUNTIME_DLL_SIZE"),
        )
        for dlls, code in cases:
            with self.subTest(code=code, dlls=dlls):
                self.assert_code(
                    code,
                    lambda dlls=dlls: parse_host_runtime_lock(lock_data(dlls=dlls)),
                )

    def test_dll_paths_are_unique_sorted_and_basenames_may_be_shared(self):
        self.assert_code(
            "DUPLICATE_HOST_RUNTIME_DLL",
            lambda: parse_host_runtime_lock(lock_data(dlls=[dll(), dll()])),
        )
        self.assert_code(
            "NONCANONICAL_HOST_RUNTIME_DLLS",
            lambda: parse_host_runtime_lock(
                lock_data(dlls=[dll("qt6core.dll"), dll()])
            ),
        )
        shared = parse_host_runtime_lock(
            lock_data(
                dlls=[
                    dll("_internal/PySide6/vcruntime140.dll"),
                    dll("_internal/vcruntime140.dll", "b" * 64),
                ]
            )
        )
        self.assertEqual(
            shared.protected_dll_basenames,
            frozenset({"vcruntime140.dll"}),
        )

    def test_import_owners_are_identifiers_and_casefold_unique(self):
        for import_name in ("a.b", "bad-name", "with space", "class", "éclair", ""):
            data = lock_data(packages=[package(imports=[import_name])])
            with self.subTest(import_name=import_name):
                self.assert_code(
                    "INVALID_HOST_RUNTIME_IMPORT",
                    lambda data=data: parse_host_runtime_lock(data),
                )
        duplicate = lock_data(packages=[package(imports=["A", "a"])])
        self.assert_code(
            "DUPLICATE_HOST_RUNTIME_IMPORT",
            lambda: parse_host_runtime_lock(duplicate),
        )
        shared_owners = parse_host_runtime_lock(
            lock_data(
            packages=[
                package("aiohttp", imports=["shared"]),
                package("paramiko", "5.0.0", ["Shared"]),
            ]
            )
        )
        self.assertEqual(
            shared_owners.import_owners["shared"],
            ("aiohttp", "paramiko"),
        )

    def test_runtime_binding_rejects_each_mismatch(self):
        runtime_lock = parse_host_runtime_lock(lock_data())
        cases = (
            (
                {
                    "expected_app_version": "1.0.1",
                    "expected_python_abi": "cp311",
                    "expected_platform": "win_amd64",
                },
                "HOST_RUNTIME_LOCK_APP_VERSION_MISMATCH",
            ),
            (
                {
                    "expected_app_version": "1.0.0",
                    "expected_python_abi": "cp312",
                    "expected_platform": "win_amd64",
                },
                "HOST_RUNTIME_LOCK_PYTHON_ABI_MISMATCH",
            ),
            (
                {
                    "expected_app_version": "1.0.0",
                    "expected_python_abi": "cp311",
                    "expected_platform": "win_arm64",
                },
                "HOST_RUNTIME_LOCK_PLATFORM_MISMATCH",
            ),
        )
        for expected, code in cases:
            with self.subTest(code=code):
                self.assert_code(
                    code,
                    lambda expected=expected: validate_host_runtime_lock(
                        runtime_lock, **expected
                    ),
                )

    def test_read_json_and_size_failures_use_stable_codes(self):
        self.assert_code(
            "INVALID_HOST_RUNTIME_LOCK_JSON",
            lambda: parse_host_runtime_lock_json(b"\xff"),
        )
        self.assert_code(
            "HOST_RUNTIME_LOCK_TOO_LARGE",
            lambda: parse_host_runtime_lock_json(
                b" " * (MAX_HOST_RUNTIME_LOCK_SIZE + 1)
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.json"
            self.assert_code(
                "HOST_RUNTIME_LOCK_READ_FAILED",
                lambda: load_host_runtime_lock(
                    missing,
                    expected_app_version="1.0.0",
                    expected_python_abi="cp311",
                    expected_platform="win_amd64",
                ),
            )

    def test_builder_rejects_duplicate_explicit_facts_after_sorting(self):
        self.assert_code(
            "DUPLICATE_HOST_RUNTIME_PACKAGE",
            lambda: build_host_runtime_lock(
                app_version="1.0.0",
                python_abi="cp311",
                platform="win_amd64",
                packages=[package(), package(imports=[])],
                dlls=[dll()],
            ),
        )
        self.assert_code(
            "INVALID_HOST_RUNTIME_IMPORT",
            lambda: build_host_runtime_lock(
                app_version="1.0.0",
                python_abi="cp311",
                platform="win_amd64",
                packages=[package(imports=["aiohttp", 1])],
                dlls=[dll()],
            ),
        )

    def test_public_entry_points_normalize_forged_dto_failures(self):
        with self.assertRaises(HostRuntimeLockError):
            HostRuntimeLock(1, Version("1.0.0"), None, (), ())
        forged = object.__new__(HostRuntimeLock)
        object.__setattr__(forged, "lock_version", 1)
        object.__setattr__(forged, "app_version", Version("1.0.0"))
        object.__setattr__(forged, "target", None)
        object.__setattr__(forged, "packages", ())
        object.__setattr__(forged, "dlls", ())
        self.assert_code(
            "INVALID_HOST_RUNTIME_LOCK",
            lambda: serialize_host_runtime_lock(forged),
        )
        self.assert_code(
            "INVALID_HOST_RUNTIME_LOCK",
            lambda: validate_host_runtime_lock(
                forged,
                expected_app_version="1.0.0",
                expected_python_abi="cp311",
                expected_platform="win_amd64",
            ),
        )


if __name__ == "__main__":
    unittest.main()
