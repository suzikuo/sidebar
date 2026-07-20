from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

import core.plugin_system.plugin_dependency_store as dependency_store_module
from core.plugin_system.interprocess_lock import (
    InterprocessFileLock,
    InterprocessLockError,
)
from core.plugin_system.plugin_dependency_store import (
    PluginDependencyStore,
    PluginDependencyStoreError,
    StoredDependency,
    StoredFile,
)
from core.plugin_system.plugin_wheel import inspect_wheel
from tests.pe_test_utils import build_test_pe
from tests.test_plugin_wheel import WheelBuilder


TARGET_PYTHON_ABI = "cp311"
TARGET_PLATFORM = "win_amd64"


class PluginDependencyStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.wheel_root = self.root / "wheels"
        self.wheel_root.mkdir()
        self.store_root = self.root / "dependency-store"
        self.store = PluginDependencyStore(self.store_root)

    def build_artifact(self, builder: WheelBuilder | None = None):
        wheel = (builder or WheelBuilder(self.wheel_root)).write()
        return inspect_wheel(
            wheel,
            target_python_abi=TARGET_PYTHON_ABI,
            target_platform=TARGET_PLATFORM,
            expected_name="demo-package",
            expected_version="2.1.0",
        )

    def materialize(self, artifact):
        return self.store.materialize(
            artifact,
            target_python_abi=TARGET_PYTHON_ABI,
            target_platform=TARGET_PLATFORM,
        )

    def assert_store_error(self, callback, expected_code=None):
        with self.assertRaises(PluginDependencyStoreError) as caught:
            callback()
        self.assertIsInstance(caught.exception.code, str)
        self.assertTrue(caught.exception.code)
        if expected_code is not None:
            self.assertEqual(caught.exception.code, expected_code)
        return caught.exception

    @staticmethod
    def rewrite_read_only(path: Path, payload: bytes):
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
        path.write_bytes(payload)
        path.chmod(stat.S_IREAD)

    @staticmethod
    def canonical_json(value) -> bytes:
        return (
            json.dumps(
                value,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    def test_materializes_purelib_and_data_files_with_verified_dto(self):
        builder = WheelBuilder(self.wheel_root)
        builder.files[
            "demo_package-2.1.0.data/purelib/demo/from_data.py"
        ] = b"FROM_DATA = True\n"
        artifact = self.build_artifact(builder)

        stored_items = self.store.materialize_many(
            (artifact,),
            target_python_abi=TARGET_PYTHON_ABI,
            target_platform=TARGET_PLATFORM,
        )

        self.assertIsInstance(stored_items, tuple)
        self.assertEqual(len(stored_items), 1)
        stored = stored_items[0]
        expected_root = (
            self.store_root
            / "objects"
            / "sha256"
            / artifact.sha256[:2]
            / artifact.sha256
        )
        self.assertIsInstance(stored, StoredDependency)
        self.assertEqual(stored.sha256, artifact.sha256)
        self.assertEqual(stored.distribution, artifact.distribution)
        self.assertEqual(stored.version, artifact.version)
        self.assertEqual(
            stored.tags,
            tuple(sorted(str(tag) for tag in artifact.tags)),
        )
        self.assertTrue(stored.root_is_purelib)
        self.assertEqual(stored.object_root, expected_root)
        self.assertEqual(stored.site_root, expected_root / "site")
        self.assertEqual(
            tuple(item.path for item in stored.files),
            artifact.installed_files,
        )
        self.assertTrue(all(isinstance(item, StoredFile) for item in stored.files))
        self.assertEqual(
            (stored.site_root / "demo" / "from_data.py").read_bytes(),
            b"FROM_DATA = True\n",
        )
        self.assertFalse((stored.site_root / "demo_package-2.1.0.data").exists())

        for item in stored.files:
            installed = stored.site_root / Path(item.path)
            payload = installed.read_bytes()
            self.assertEqual(item.size, len(payload))
            self.assertEqual(item.sha256, hashlib.sha256(payload).hexdigest())

        verified = self.store.get_verified(
            artifact.sha256,
            expected_artifact=artifact,
        )
        self.assertEqual(verified, stored)
        with self.assertRaises(FrozenInstanceError):
            stored.sha256 = "0" * 64
        with self.assertRaises(FrozenInstanceError):
            stored.files[0].size = 0

    def test_reusing_existing_object_does_not_change_final_mtimes(self):
        artifact = self.build_artifact()
        first = self.materialize(artifact)
        receipt = first.object_root / "receipt.json"
        installed = first.site_root / "demo" / "__init__.py"
        marker = 946_684_800_000_000_000
        for path in (first.object_root, receipt, installed):
            os.utime(path, ns=(marker, marker))

        second = self.materialize(artifact)

        self.assertEqual(second, first)
        for path in (first.object_root, receipt, installed):
            self.assertEqual(path.stat().st_mtime_ns, marker)

    def test_source_changed_after_inspection_is_rejected_before_publish(self):
        artifact = self.build_artifact()
        artifact.path.write_bytes(artifact.path.read_bytes() + b"changed")
        expected_root = (
            self.store_root
            / "objects"
            / "sha256"
            / artifact.sha256[:2]
            / artifact.sha256
        )

        self.assert_store_error(lambda: self.materialize(artifact))

        self.assertFalse(expected_root.exists())
        staging = self.store_root / "staging"
        self.assertTrue(staging.is_dir())
        self.assertEqual(list(staging.iterdir()), [])

    def test_tampered_receipt_is_rejected_without_replacing_object(self):
        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        receipt = stored.object_root / "receipt.json"
        tampered = b"{}\n"
        receipt.chmod(0o600)
        receipt.write_bytes(tampered)

        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            )
        )
        self.assertEqual(receipt.read_bytes(), tampered)
        self.assert_store_error(lambda: self.materialize(artifact))
        self.assertEqual(receipt.read_bytes(), tampered)
        self.assertTrue(stored.site_root.is_dir())

    def test_tampered_installed_file_is_rejected_without_repairing_object(self):
        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        installed = stored.site_root / "demo" / "__init__.py"
        tampered = b"VALUE = 9\n"
        installed.chmod(0o600)
        installed.write_bytes(tampered)

        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            )
        )
        self.assertEqual(installed.read_bytes(), tampered)
        self.assert_store_error(lambda: self.materialize(artifact))
        self.assertEqual(installed.read_bytes(), tampered)

    def test_matching_file_and_receipt_tamper_is_rejected_by_artifact_anchor(self):
        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        installed = stored.site_root / "demo" / "__init__.py"
        receipt = stored.object_root / "receipt.json"
        tampered = b"VALUE = 404\n"
        installed.chmod(stat.S_IREAD | stat.S_IWRITE)
        installed.write_bytes(tampered)
        installed.chmod(stat.S_IREAD)

        value = json.loads(receipt.read_text(encoding="utf-8"))
        file_entry = next(
            item for item in value["files"] if item["path"] == "demo/__init__.py"
        )
        file_entry["size"] = len(tampered)
        file_entry["sha256"] = hashlib.sha256(tampered).hexdigest()
        self.rewrite_read_only(receipt, self.canonical_json(value))

        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )

    def test_private_wheel_snapshot_is_not_part_of_committed_object(self):
        artifact = self.build_artifact()

        stored = self.materialize(artifact)

        self.assertEqual(
            {path.name for path in stored.object_root.iterdir()},
            {"site", "receipt.json"},
        )
        self.assertEqual(
            [path for path in stored.object_root.rglob("*") if path.suffix == ".whl"],
            [],
        )
        self.assertEqual(list((self.store_root / "staging").iterdir()), [])
        self.assertTrue((self.store_root / ".store.lock").is_file())

    def test_native_dto_uses_absolute_site_paths_and_dll_directories(self):
        builder = WheelBuilder(
            self.wheel_root,
            tag="cp311-cp311-win_amd64",
            root_is_purelib=False,
        )
        builder.files["demo/fast.cp311-win_amd64.pyd"] = build_test_pe()
        builder.files["demo/libs/helper.dll"] = build_test_pe(
            export_name="not_python"
        )
        builder.files["demo/libs/second.dll"] = build_test_pe(
            export_name="not_python"
        )
        artifact = self.build_artifact(builder)

        stored = self.materialize(artifact)

        self.assertFalse(stored.root_is_purelib)
        self.assertEqual(
            stored.native_extensions,
            (stored.site_root / "demo" / "fast.cp311-win_amd64.pyd",),
        )
        self.assertEqual(
            stored.dlls,
            (
                stored.site_root / "demo" / "libs" / "helper.dll",
                stored.site_root / "demo" / "libs" / "second.dll",
            ),
        )
        self.assertEqual(
            stored.dll_directories,
            (stored.site_root / "demo" / "libs",),
        )
        self.assertTrue(all(path.is_absolute() for path in stored.native_extensions))
        self.assertTrue(all(path.is_absolute() for path in stored.dlls))
        self.assertTrue(all(path.is_absolute() for path in stored.dll_directories))

    def test_invalid_digest_and_expected_artifact_mismatch_are_rejected(self):
        for digest in (
            "",
            "abc",
            "0" * 63,
            "0" * 65,
            "A" * 64,
            "../" + "0" * 61,
        ):
            with self.subTest(digest=digest):
                self.assert_store_error(lambda value=digest: self.store.get_verified(value))

        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        self.assert_store_error(
            lambda: self.store.get_verified(artifact.sha256),
            "DEPENDENCY_ARTIFACT_REQUIRED",
        )
        wrong_artifact = replace(artifact, distribution="other-package")
        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=wrong_artifact,
            )
        )
        self.assertEqual(
            self.store.get_verified(artifact.sha256, expected_artifact=artifact),
            stored,
        )

    def test_wrong_target_is_rejected_before_and_after_cache_hit(self):
        artifact = self.build_artifact()
        cold_store = PluginDependencyStore(self.root / "cold-target-store")

        for store in (cold_store, self.store):
            if store is self.store:
                self.materialize(artifact)
            self.assert_store_error(
                lambda current_store=store: current_store.materialize(
                    artifact,
                    target_python_abi="cp312",
                    target_platform=TARGET_PLATFORM,
                ),
                "DEPENDENCY_ARTIFACT_TARGET_MISMATCH",
            )

    def test_writable_receipt_is_rejected_even_when_content_is_unchanged(self):
        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        receipt = stored.object_root / "receipt.json"
        original = receipt.read_bytes()

        receipt.chmod(stat.S_IREAD | stat.S_IWRITE)

        self.assertEqual(receipt.read_bytes(), original)
        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )
        self.assertEqual(receipt.read_bytes(), original)

    def test_receipt_schema_duplicate_key_and_address_mismatch_are_rejected(self):
        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        receipt = stored.object_root / "receipt.json"
        original = receipt.read_bytes()
        value = json.loads(original.decode("utf-8"))

        with_unknown = dict(value)
        with_unknown["unexpected"] = True
        self.rewrite_read_only(receipt, self.canonical_json(with_unknown))
        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )

        float_version = dict(value)
        float_version["receipt_version"] = 1.0
        self.rewrite_read_only(receipt, self.canonical_json(float_version))
        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )

        duplicate_key = b'{"receipt_version":1,' + original[1:]
        self.rewrite_read_only(receipt, duplicate_key)
        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )

        wrong_address = dict(value)
        wrong_address["wheel_sha256"] = (
            "f" * 64 if artifact.sha256 != "f" * 64 else "e" * 64
        )
        self.rewrite_read_only(receipt, self.canonical_json(wrong_address))
        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )

    def test_extra_site_file_and_empty_directory_are_rejected(self):
        artifact = self.build_artifact()
        cases = ("extra-file", "empty-directory")

        for case in cases:
            with self.subTest(case=case):
                store = PluginDependencyStore(self.root / case)
                stored = store.materialize(
                    artifact,
                    target_python_abi=TARGET_PYTHON_ABI,
                    target_platform=TARGET_PLATFORM,
                )
                stored.site_root.chmod(
                    stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC
                )
                if case == "extra-file":
                    (stored.site_root / "unexpected.py").write_bytes(b"bad\n")
                else:
                    empty = stored.site_root / "empty"
                    empty.mkdir()
                    empty.chmod(stat.S_IREAD | stat.S_IEXEC)
                stored.site_root.chmod(stat.S_IREAD | stat.S_IEXEC)

                self.assert_store_error(
                    lambda current_store=store: current_store.get_verified(
                        artifact.sha256,
                        expected_artifact=artifact,
                    ),
                    "DEPENDENCY_OBJECT_CORRUPT",
                )

    def test_hard_link_to_committed_file_is_rejected_when_supported(self):
        artifact = self.build_artifact()
        stored = self.materialize(artifact)
        installed = stored.site_root / "demo" / "__init__.py"
        external_link = self.root / "linked-init.py"
        try:
            os.link(installed, external_link)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"Hard links are unavailable on this filesystem: {error}")

        self.assert_store_error(
            lambda: self.store.get_verified(
                artifact.sha256,
                expected_artifact=artifact,
            ),
            "DEPENDENCY_OBJECT_CORRUPT",
        )

    def test_matching_orphan_staging_directory_is_cleaned_before_materialize(self):
        artifact = self.build_artifact()
        orphan = self.store_root / "staging" / (
            f"{artifact.sha256[:16]}.{os.getpid()}.{'a' * 16}.tmp"
        )
        nested = orphan / "partial" / "site"
        nested.mkdir(parents=True)
        (nested / "partial.py").write_bytes(b"incomplete\n")

        stored = self.materialize(artifact)

        self.assertFalse(orphan.exists())
        self.assertTrue(stored.object_root.is_dir())
        self.assertEqual(list((self.store_root / "staging").iterdir()), [])

    def test_publish_rename_failure_leaves_no_final_or_staging_object(self):
        artifact = self.build_artifact()
        final_path = (
            self.store_root
            / "objects"
            / "sha256"
            / artifact.sha256[:2]
            / artifact.sha256
        )

        with patch.object(
            dependency_store_module.os,
            "rename",
            side_effect=OSError("simulated publish failure"),
        ):
            self.assert_store_error(
                lambda: self.materialize(artifact),
                "DEPENDENCY_STORE_IO_ERROR",
            )

        self.assertFalse(final_path.exists())
        self.assertEqual(list((self.store_root / "staging").iterdir()), [])

    def test_public_call_reports_busy_while_another_store_lock_is_held(self):
        artifact = self.build_artifact()
        self.materialize(artifact)
        competing_lock = InterprocessFileLock(self.store_root, ".store.lock")

        try:
            with competing_lock.acquire():
                try:
                    self.store.get_verified(
                        artifact.sha256,
                        expected_artifact=artifact,
                    )
                except PluginDependencyStoreError as error:
                    self.assertEqual(error.code, "DEPENDENCY_STORE_BUSY")
                else:
                    self.skipTest(
                        "This platform does not contend separate same-process locks."
                    )
        except InterprocessLockError as error:
            self.skipTest(f"Filesystem locking is unavailable: {error}")


if __name__ == "__main__":
    unittest.main()
