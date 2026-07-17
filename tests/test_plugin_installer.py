import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.plugin_system.plugin_installer import (
    PluginInstaller,
    PluginInstallerError,
)
from core.plugin_system.plugin_manifest import HostEnvironment
from core.plugin_system.plugin_package import stage_plugin_package


class PluginInstallerTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.user_root = self.root / "user-plugins"
        self.transaction_root = self.root / "plugin-transactions"
        self.installer = PluginInstaller(
            self.user_root,
            self.transaction_root,
            host_environment=self._host(),
        )

    def _write_package(
        self,
        *,
        plugin_id: str = "sample_plugin",
        version: str = "1.0.0",
        marker: str = "new",
    ) -> Path:
        package_path = self.root / f"{plugin_id}-{version}.atplugin"
        plugin_source = f"MARKER = {marker!r}\n"
        manifest = {
            "manifest_version": 2,
            "id": plugin_id,
            "name": "Sample Plugin",
            "version": version,
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
                "plugin.py": hashlib.sha256(plugin_source.encode("utf-8")).hexdigest()
            },
            "requires_restart": False,
        }
        with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("plugin.py", plugin_source)
        return package_path

    def _write_installed(
        self,
        plugin_id: str = "sample_plugin",
        version: str = "1.0.0",
        marker: str = "old",
    ) -> Path:
        plugin_dir = self.user_root / plugin_id
        plugin_dir.mkdir(parents=True)
        manifest = {
            "id": plugin_id,
            "name": "Sample Plugin",
            "version": version,
            "entry": "plugin.py",
            "class": "SamplePlugin",
        }
        (plugin_dir / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        (plugin_dir / "plugin.py").write_text(
            f"MARKER = {marker!r}\n", encoding="utf-8"
        )
        return plugin_dir

    def _version(self, plugin_dir: Path) -> str:
        return json.loads((plugin_dir / "manifest.json").read_text(encoding="utf-8"))[
            "version"
        ]

    @staticmethod
    def _host():
        return HostEnvironment(
            app_version="1.0.0",
            api_version="1.0",
            python_abi="cp311",
            platform_tag="win_amd64",
            host_packages={},
        )

    def _rewrite_transaction(self, transaction, **changes):
        metadata_path = (
            self.transaction_root
            / "transactions"
            / f"{transaction.transaction_id}.json"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.update(changes)
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return self.installer.get_transaction(transaction.transaction_id)

    def test_new_install_is_pending_then_applied_idempotently(self):
        package_path = self._write_package()

        queued = self.installer.import_package(package_path)
        duplicate = self.installer.import_package(package_path)

        self.assertEqual(queued, duplicate)
        self.assertEqual(queued.state, "pending")
        with self.assertRaises(PluginInstallerError) as conflicting:
            self.installer.import_package(self._write_package(version="2.0.0"))
        self.assertEqual(conflicting.exception.code, "PLUGIN_TRANSACTION_PENDING")
        self.assertTrue(
            (self.transaction_root / "pending" / queued.transaction_id).is_dir()
        )
        installed = self.installer.apply_pending(queued.transaction_id)
        repeated = self.installer.apply_pending(queued.transaction_id)

        self.assertEqual(installed.state, "applied")
        self.assertEqual(repeated, installed)
        self.assertEqual(self._version(self.user_root / "sample_plugin"), "1.0.0")
        metadata = json.loads(
            (
                self.transaction_root
                / "transactions"
                / f"{queued.transaction_id}.json"
            ).read_text(encoding="utf-8")
        )
        self.assertNotIn("target_path", metadata)
        self.assertNotIn(str(self.user_root), json.dumps(metadata))

    def test_import_hashes_the_same_private_snapshot_that_was_staged(self):
        package_path = self._write_package(marker="staged")
        staged_package = package_path.read_bytes()
        replacement_path = self._write_package(
            plugin_id="replacement_plugin",
            version="9.0.0",
            marker="replacement",
        )
        replacement_package = replacement_path.read_bytes()

        def stage_then_replace(snapshot_path, staging_root, **kwargs):
            staged = stage_plugin_package(snapshot_path, staging_root, **kwargs)
            package_path.write_bytes(replacement_package)
            return staged

        with patch(
            "core.plugin_system.plugin_installer.stage_plugin_package",
            side_effect=stage_then_replace,
        ):
            transaction = self.installer.import_package(package_path)

        pending_plugin = (
            self.transaction_root
            / "pending"
            / transaction.transaction_id
            / "plugin.py"
        )
        self.assertEqual(package_path.read_bytes(), replacement_package)
        self.assertEqual(
            transaction.package_sha256,
            hashlib.sha256(staged_package).hexdigest(),
        )
        self.assertEqual(pending_plugin.read_text(encoding="utf-8"), "MARKER = 'staged'\n")

    def test_snapshot_copy_failure_is_normalized_and_clean(self):
        package_path = self._write_package()
        with patch(
            "core.plugin_system.plugin_installer.shutil.copyfile",
            side_effect=OSError(errno.EIO, "source package cannot be copied"),
        ):
            with self.assertRaises(PluginInstallerError) as caught:
                self.installer.import_package(package_path)

        self.assertEqual(caught.exception.code, "TRANSACTION_IO_ERROR")
        self.assertEqual(list((self.transaction_root / "pending").iterdir()), [])
        self.assertEqual(self.installer.list_transactions(), [])

    def test_snapshot_cleanup_failure_aborts_before_transaction(self):
        package_path = self._write_package()
        original_rmtree = shutil.rmtree

        def fail_snapshot_cleanup(path, *args, **kwargs):
            if Path(path).name.startswith(".package-input-"):
                raise PermissionError(errno.EACCES, "snapshot is locked")
            return original_rmtree(path, *args, **kwargs)

        with patch(
            "core.plugin_system.plugin_installer.shutil.rmtree",
            side_effect=fail_snapshot_cleanup,
        ):
            with self.assertRaises(PluginInstallerError) as caught:
                self.installer.import_package(package_path)

        self.assertEqual(caught.exception.code, "FILE_LOCKED")
        self.assertEqual(self.installer.list_transactions(), [])
        pending_entries = list((self.transaction_root / "pending").iterdir())
        self.assertEqual(len(pending_entries), 1)
        self.assertTrue(pending_entries[0].name.startswith(".package-input-"))
        self.assertEqual(self.installer.recover_transactions(), [])
        self.assertEqual(list((self.transaction_root / "pending").iterdir()), [])

    def test_legacy_transaction_metadata_without_load_health_is_compatible(self):
        transaction = self.installer.import_package(self._write_package())
        metadata_path = (
            self.transaction_root
            / "transactions"
            / f"{transaction.transaction_id}.json"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertFalse(metadata.pop("load_verified"))
        self.assertRegex(metadata.pop("content_sha256"), r"[0-9a-f]{64}")
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        legacy = self.installer.get_transaction(transaction.transaction_id)

        self.assertIsNone(legacy.load_verified)
        self.assertEqual(
            self.installer.list_transactions(plugin_id="sample_plugin"),
            [legacy],
        )

    def test_applied_install_can_be_marked_load_verified(self):
        pending = self.installer.import_package(self._write_package())
        self.assertFalse(pending.load_verified)
        with self.assertRaises(PluginInstallerError) as invalid_state:
            self.installer.mark_load_verified(pending.transaction_id)
        self.assertEqual(invalid_state.exception.code, "INVALID_TRANSACTION_STATE")

        applied = self.installer.apply_pending(pending.transaction_id)
        verified = self.installer.mark_load_verified(pending.transaction_id)
        repeated = self.installer.mark_load_verified(pending.transaction_id)

        self.assertFalse(applied.load_verified)
        self.assertTrue(verified.load_verified)
        self.assertEqual(repeated, verified)
        self.assertTrue(
            self.installer.get_transaction(pending.transaction_id).load_verified
        )

        uninstall = self.installer.stage_uninstall("missing_plugin")
        self.assertIsNone(uninstall.load_verified)
        with self.assertRaises(PluginInstallerError) as invalid_operation:
            self.installer.mark_load_verified(uninstall.transaction_id)
        self.assertEqual(
            invalid_operation.exception.code,
            "INVALID_TRANSACTION_OPERATION",
        )

    def test_upgrade_keeps_backup_and_can_rollback(self):
        target = self._write_installed(version="1.0.0")
        transaction = self.installer.import_package(
            self._write_package(version="2.0.0")
        )

        applied = self.installer.apply_pending(transaction.transaction_id)

        self.assertTrue(applied.had_previous)
        self.assertEqual(self._version(target), "2.0.0")
        backup = self.transaction_root / "backups" / transaction.transaction_id
        self.assertEqual(self._version(backup), "1.0.0")

        rolled_back = self.installer.rollback(transaction.transaction_id)
        repeated = self.installer.rollback(transaction.transaction_id)

        self.assertEqual(rolled_back.state, "rolled_back")
        self.assertEqual(repeated, rolled_back)
        self.assertEqual(self._version(target), "1.0.0")
        self.assertEqual(
            self._version(
                self.transaction_root / "pending" / transaction.transaction_id
            ),
            "2.0.0",
        )

    def test_request_rollback_is_restart_oriented_and_blocks_new_transactions(self):
        target = self._write_installed(version="1.0.0")
        package = self._write_package(version="2.0.0")
        transaction = self.installer.import_package(package)
        applied = self.installer.apply_pending(transaction.transaction_id)
        backup = self.transaction_root / "backups" / transaction.transaction_id
        pending = self.transaction_root / "pending" / transaction.transaction_id

        requested = self.installer.request_rollback(transaction.transaction_id)
        repeated = self.installer.request_rollback(transaction.transaction_id)

        self.assertEqual(requested.state, "rollback_pending")
        self.assertEqual(repeated, requested)
        self.assertEqual(requested.load_verified, applied.load_verified)
        self.assertEqual(self._version(target), "2.0.0")
        self.assertEqual(self._version(backup), "1.0.0")
        self.assertFalse(pending.exists())
        self.assertEqual(
            self.installer.list_transactions(
                plugin_id="sample_plugin",
                states={"rollback_pending"},
            ),
            [requested],
        )
        self.assertEqual(self.installer.recover_transactions(), [requested])
        self.assertEqual(self._version(target), "2.0.0")

        with self.assertRaises(PluginInstallerError) as blocked_import:
            self.installer.import_package(package)
        self.assertEqual(blocked_import.exception.code, "PLUGIN_ROLLBACK_PENDING")
        with self.assertRaises(PluginInstallerError) as blocked_uninstall:
            self.installer.stage_uninstall("sample_plugin")
        self.assertEqual(
            blocked_uninstall.exception.code,
            "PLUGIN_ROLLBACK_PENDING",
        )

    def test_rollback_executes_a_restart_pending_install_rollback(self):
        target = self._write_installed(version="1.0.0")
        transaction = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        self.installer.apply_pending(transaction.transaction_id)
        self.installer.request_rollback(transaction.transaction_id)

        rolled_back = self.installer.rollback(transaction.transaction_id)

        self.assertEqual(rolled_back.state, "rolled_back")
        self.assertEqual(self._version(target), "1.0.0")
        self.assertEqual(
            self._version(
                self.transaction_root / "pending" / transaction.transaction_id
            ),
            "2.0.0",
        )

    def test_rollback_pending_transaction_supersedes_older_versions(self):
        target = self._write_installed(version="1.0.0")
        version_two = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        self.installer.apply_pending(version_two.transaction_id)
        version_three = self.installer.import_package(
            self._write_package(version="3.0.0")
        )
        self.installer.apply_pending(version_three.transaction_id)
        requested = self.installer.request_rollback(version_three.transaction_id)

        with self.assertRaises(PluginInstallerError) as superseded:
            self.installer.rollback(version_two.transaction_id)

        self.assertEqual(requested.state, "rollback_pending")
        self.assertEqual(superseded.exception.code, "SUPERSEDED_TRANSACTION")
        self.assertEqual(self._version(target), "3.0.0")

    def test_rollback_pending_state_is_rejected_for_uninstall_metadata(self):
        uninstall = self.installer.stage_uninstall("missing_plugin")

        with self.assertRaises(PluginInstallerError) as corrupt:
            self._rewrite_transaction(uninstall, state="rollback_pending")

        self.assertEqual(corrupt.exception.code, "TRANSACTION_CORRUPT")

    def test_locked_upgrade_rolls_back_and_returns_stable_error(self):
        target = self._write_installed(version="1.0.0")
        transaction = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        pending = self.transaction_root / "pending" / transaction.transaction_id
        original_rename = self.installer._rename_path
        failed_once = False

        def fail_new_version(source, destination):
            nonlocal failed_once
            if source == pending and destination == target and not failed_once:
                failed_once = True
                raise PermissionError(errno.EACCES, "plugin file is locked")
            return original_rename(source, destination)

        with patch.object(self.installer, "_rename_path", side_effect=fail_new_version):
            with self.assertRaises(PluginInstallerError) as caught:
                self.installer.apply_pending(transaction.transaction_id)

        self.assertEqual(caught.exception.code, "FILE_LOCKED")
        self.assertEqual(self._version(target), "1.0.0")
        self.assertTrue(pending.is_dir())
        saved = self.installer.get_transaction(transaction.transaction_id)
        self.assertEqual(saved.state, "rolled_back")
        self.assertEqual(saved.error_code, "FILE_LOCKED")

    def test_uninstall_only_removes_user_override_and_is_reversible(self):
        bundled_root = self.root / "bundled"
        bundled_plugin = bundled_root / "sample_plugin"
        bundled_plugin.mkdir(parents=True)
        (bundled_plugin / "plugin.py").write_text("BUNDLED = True\n", encoding="utf-8")
        target = self._write_installed()

        transaction = self.installer.uninstall("sample_plugin")

        self.assertEqual(transaction.state, "applied")
        self.assertFalse(target.exists())
        self.assertTrue(bundled_plugin.is_dir())
        self.assertTrue(
            (self.transaction_root / "backups" / transaction.transaction_id).is_dir()
        )

        restored = self.installer.rollback(transaction.transaction_id)
        self.assertEqual(restored.state, "rolled_back")
        self.assertTrue(target.is_dir())
        self.assertTrue(bundled_plugin.is_dir())

        missing = self.installer.uninstall("not_installed")
        self.assertEqual(missing.state, "applied")
        self.assertFalse(missing.had_previous)

    def test_list_transactions_is_newest_first_and_supports_filters(self):
        first = self.installer.stage_uninstall("missing_first")
        pending = self.installer.import_package(
            self._write_package(plugin_id="pending_plugin")
        )
        last = self.installer.stage_uninstall("missing_last")

        expected = sorted(
            [first, pending, last],
            key=lambda transaction: (
                transaction.created_at_ns,
                transaction.transaction_id,
            ),
            reverse=True,
        )
        self.assertEqual(self.installer.list_transactions(), expected)
        self.assertEqual(
            self.installer.list_transactions(plugin_id="pending_plugin"),
            [pending],
        )
        self.assertEqual(
            self.installer.list_transactions(states={"pending"}),
            [pending],
        )
        self.assertEqual(
            self.installer.list_transactions(states=set()),
            [],
        )

    def test_list_transactions_rejects_invalid_filters_and_corrupt_metadata(self):
        with self.assertRaises(PluginInstallerError) as invalid_plugin:
            self.installer.list_transactions(plugin_id="../outside")
        self.assertEqual(invalid_plugin.exception.code, "INVALID_PLUGIN_ID")

        for states in ("pending", {"unknown"}, 42):
            with self.subTest(states=states):
                with self.assertRaises(PluginInstallerError) as invalid_states:
                    self.installer.list_transactions(states=states)
                self.assertEqual(
                    invalid_states.exception.code,
                    "INVALID_TRANSACTION_FILTER",
                )

        transaction_id = "a" * 32
        metadata_path = (
            self.transaction_root / "transactions" / f"{transaction_id}.json"
        )
        metadata_path.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(PluginInstallerError) as corrupt:
            self.installer.list_transactions()
        self.assertEqual(corrupt.exception.code, "TRANSACTION_CORRUPT")

    def test_failed_transaction_blocks_import_and_uninstall_and_stays_visible(self):
        original_package = self._write_package()
        failed = self.installer.import_package(original_package)
        failed = self._rewrite_transaction(
            failed,
            state="failed",
            error_code="ROLLBACK_FAILED",
            error_message="manual repair required",
        )

        for package_path in (
            original_package,
            self._write_package(version="2.0.0"),
        ):
            with self.subTest(package_path=package_path.name):
                with self.assertRaises(PluginInstallerError) as blocked_import:
                    self.installer.import_package(package_path)
                self.assertEqual(
                    blocked_import.exception.code,
                    "PLUGIN_TRANSACTION_FAILED",
                )
                self.assertEqual(
                    blocked_import.exception.transaction_id,
                    failed.transaction_id,
                )

        with self.assertRaises(PluginInstallerError) as blocked_uninstall:
            self.installer.stage_uninstall("sample_plugin")
        self.assertEqual(
            blocked_uninstall.exception.code,
            "PLUGIN_TRANSACTION_FAILED",
        )
        self.assertEqual(
            blocked_uninstall.exception.transaction_id,
            failed.transaction_id,
        )

        self.assertEqual(
            self.installer.list_transactions(
                plugin_id="sample_plugin",
                states={"failed"},
            ),
            [failed],
        )
        self.assertEqual(self.installer.recover_transactions(), [failed])
        self.assertEqual(
            sorted(path.name for path in self.installer.pending_root.iterdir()),
            [failed.transaction_id],
        )

    def test_invalid_ids_metadata_and_root_layout_cannot_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        with self.assertRaises(PluginInstallerError) as invalid_id:
            self.installer.stage_uninstall("../outside")
        self.assertEqual(invalid_id.exception.code, "INVALID_PLUGIN_ID")
        self.assertTrue(outside.is_dir())

        transaction_id = "a" * 32
        metadata_path = (
            self.transaction_root / "transactions" / f"{transaction_id}.json"
        )
        metadata_path.write_text(
            json.dumps(
                {
                    "transaction_id": transaction_id,
                    "operation": "uninstall",
                    "plugin_id": "../outside",
                    "version": None,
                    "state": "applying",
                    "created_at_ns": 1,
                    "had_previous": True,
                    "package_sha256": None,
                    "error_code": None,
                    "error_message": None,
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(PluginInstallerError) as corrupt:
            self.installer.recover_transactions()
        self.assertEqual(corrupt.exception.code, "TRANSACTION_CORRUPT")
        self.assertTrue(outside.is_dir())

        with self.assertRaises(PluginInstallerError) as nested_root:
            PluginInstaller(
                self.root / "other-user-plugins",
                self.root / "other-user-plugins" / "transactions",
            )
        self.assertEqual(nested_root.exception.code, "INVALID_ROOT_LAYOUT")

    def test_interrupted_upgrade_recovery_is_repeatable(self):
        target = self._write_installed(version="1.0.0")
        transaction = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        metadata_path = (
            self.transaction_root
            / "transactions"
            / f"{transaction.transaction_id}.json"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["state"] = "applying"
        metadata["had_previous"] = True
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        backup = self.transaction_root / "backups" / transaction.transaction_id
        os.replace(target, backup)

        first = self.installer.recover_transactions()
        second = self.installer.recover_transactions()

        recovered = next(
            item for item in first if item.transaction_id == transaction.transaction_id
        )
        repeated = next(
            item for item in second if item.transaction_id == transaction.transaction_id
        )
        self.assertEqual(recovered.state, "rolled_back")
        self.assertEqual(repeated.state, "rolled_back")
        self.assertEqual(self._version(target), "1.0.0")
        self.assertEqual(
            self._version(
                self.transaction_root / "pending" / transaction.transaction_id
            ),
            "2.0.0",
        )

    def test_interrupted_explicit_rollback_recovery_is_repeatable(self):
        target = self._write_installed(version="1.0.0")
        transaction = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        self.installer.apply_pending(transaction.transaction_id)
        metadata_path = (
            self.transaction_root
            / "transactions"
            / f"{transaction.transaction_id}.json"
        )
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["state"] = "rolling_back"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        pending = self.transaction_root / "pending" / transaction.transaction_id
        os.replace(target, pending)

        first = self.installer.recover_transactions()
        second = self.installer.recover_transactions()

        recovered = next(
            item for item in first if item.transaction_id == transaction.transaction_id
        )
        repeated = next(
            item for item in second if item.transaction_id == transaction.transaction_id
        )
        self.assertEqual(recovered.state, "rolled_back")
        self.assertEqual(repeated.state, "rolled_back")
        self.assertEqual(self._version(target), "1.0.0")
        self.assertEqual(self._version(pending), "2.0.0")

    def test_older_transaction_cannot_rollback_across_newer_version(self):
        target = self._write_installed(version="1.0.0")
        version_two = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        self.installer.apply_pending(version_two.transaction_id)
        version_three = self.installer.import_package(
            self._write_package(version="3.0.0")
        )
        self.installer.apply_pending(version_three.transaction_id)

        with self.assertRaises(PluginInstallerError) as superseded:
            self.installer.rollback(version_two.transaction_id)

        self.assertEqual(superseded.exception.code, "SUPERSEDED_TRANSACTION")
        self.assertEqual(self._version(target), "3.0.0")
        self.installer.rollback(version_three.transaction_id)
        self.assertEqual(self._version(target), "2.0.0")
        self.installer.rollback(version_two.transaction_id)
        self.assertEqual(self._version(target), "1.0.0")

    def test_generation_blocks_rollback_when_wall_clock_moves_backward(self):
        target = self._write_installed(version="1.0.0")
        with patch(
            "core.plugin_system.plugin_installer.time.time_ns",
            side_effect=[200, 100],
        ):
            version_two = self.installer.import_package(
                self._write_package(version="2.0.0")
            )
            self.installer.apply_pending(version_two.transaction_id)
            version_three = self.installer.import_package(
                self._write_package(version="3.0.0")
            )
            self.installer.apply_pending(version_three.transaction_id)

        self.assertEqual(version_two.generation, 1)
        self.assertEqual(version_three.generation, 2)
        self.assertLess(version_three.created_at_ns, version_two.created_at_ns)
        with self.assertRaises(PluginInstallerError) as superseded:
            self.installer.rollback(version_two.transaction_id)

        self.assertEqual(superseded.exception.code, "SUPERSEDED_TRANSACTION")
        self.assertEqual(self._version(target), "3.0.0")

    def test_older_transaction_cannot_rollback_across_newer_failed_transaction(self):
        target = self._write_installed(version="1.0.0")
        version_two = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        self.installer.apply_pending(version_two.transaction_id)
        version_three = self.installer.import_package(
            self._write_package(version="3.0.0")
        )
        failed = self._rewrite_transaction(
            version_three,
            state="failed",
            created_at_ns=version_two.created_at_ns + 1,
            error_code="ROLLBACK_FAILED",
            error_message="manual repair required",
        )

        with self.assertRaises(PluginInstallerError) as superseded:
            self.installer.rollback(version_two.transaction_id)

        self.assertEqual(superseded.exception.code, "SUPERSEDED_TRANSACTION")
        self.assertEqual(
            superseded.exception.transaction_id,
            version_two.transaction_id,
        )
        self.assertEqual(self._version(target), "2.0.0")
        self.assertEqual(
            self.installer.list_transactions(
                plugin_id="sample_plugin",
                states={"failed"},
            ),
            [failed],
        )

    def test_missing_upgrade_backup_does_not_move_current_version(self):
        target = self._write_installed(version="1.0.0")
        transaction = self.installer.import_package(
            self._write_package(version="2.0.0")
        )
        self.installer.apply_pending(transaction.transaction_id)
        backup = self.transaction_root / "backups" / transaction.transaction_id
        for child in backup.iterdir():
            child.unlink()
        backup.rmdir()

        with self.assertRaises(PluginInstallerError) as missing_backup:
            self.installer.rollback(transaction.transaction_id)

        self.assertEqual(missing_backup.exception.code, "BACKUP_NOT_FOUND")
        self.assertEqual(self._version(target), "2.0.0")
        self.assertFalse(
            (self.transaction_root / "pending" / transaction.transaction_id).exists()
        )

    def test_pending_manifest_is_revalidated_before_apply(self):
        transaction = self.installer.import_package(self._write_package())
        transaction = self._rewrite_transaction(
            transaction, content_sha256=None
        )
        pending_manifest = (
            self.transaction_root
            / "pending"
            / transaction.transaction_id
            / "manifest.json"
        )
        manifest = json.loads(pending_manifest.read_text(encoding="utf-8"))
        manifest["id"] = "different_plugin"
        pending_manifest.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(PluginInstallerError) as invalid:
            self.installer.apply_pending(transaction.transaction_id)

        self.assertEqual(invalid.exception.code, "PENDING_INVALID")
        self.assertFalse((self.user_root / "sample_plugin").exists())
        self.assertEqual(
            self.installer.get_transaction(transaction.transaction_id).state,
            "rolled_back",
        )

    def test_pending_v2_compatibility_is_revalidated_before_apply(self):
        installer = PluginInstaller(
            self.user_root,
            self.transaction_root,
            host_environment=self._host(),
        )
        package = self.root / "compatible.atplugin"
        plugin_source = "class SamplePlugin: pass\n"
        manifest = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "2.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1.0.0,<2.0.0",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {"host": [], "python": []},
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {
                "plugin.py": hashlib.sha256(
                    plugin_source.encode("utf-8")
                ).hexdigest()
            },
            "requires_restart": True,
        }
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("plugin.py", plugin_source)
        transaction = installer.import_package(package)
        self._rewrite_transaction(transaction, content_sha256=None)
        pending_manifest = (
            self.transaction_root
            / "pending"
            / transaction.transaction_id
            / "manifest.json"
        )
        manifest["compatibility"]["python_abi"] = "cp312"
        pending_manifest.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(PluginInstallerError) as incompatible:
            installer.apply_pending(transaction.transaction_id)

        self.assertEqual(incompatible.exception.code, "INCOMPATIBLE_PYTHON_ABI")
        self.assertFalse((self.user_root / "sample_plugin").exists())
        self.assertEqual(
            installer.get_transaction(transaction.transaction_id).state,
            "rolled_back",
        )

    def test_pending_v2_file_hash_is_revalidated_before_apply(self):
        installer = PluginInstaller(
            self.user_root,
            self.transaction_root,
            host_environment=self._host(),
        )
        package = self.root / "integrity.atplugin"
        plugin_source = "class SamplePlugin: pass\n"
        manifest = {
            "manifest_version": 2,
            "id": "sample_plugin",
            "name": "Sample Plugin",
            "version": "2.0.0",
            "entry": "plugin.py",
            "class": "SamplePlugin",
            "api_version": "1.0",
            "compatibility": {
                "app": ">=1.0.0,<2.0.0",
                "python_abi": "cp311",
                "platform": "win_amd64",
            },
            "dependencies": {"host": [], "python": []},
            "ui": {"type": "native"},
            "native_modules": [],
            "files": {
                "plugin.py": hashlib.sha256(
                    plugin_source.encode("utf-8")
                ).hexdigest()
            },
            "requires_restart": True,
        }
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest))
            archive.writestr("plugin.py", plugin_source)
        transaction = installer.import_package(package)
        self._rewrite_transaction(transaction, content_sha256=None)
        pending_plugin = (
            self.transaction_root
            / "pending"
            / transaction.transaction_id
            / "plugin.py"
        )
        pending_plugin.write_text("tampered\n", encoding="utf-8")

        with self.assertRaises(PluginInstallerError) as mismatch:
            installer.apply_pending(transaction.transaction_id)

        self.assertEqual(mismatch.exception.code, "FILE_HASH_MISMATCH")
        self.assertFalse((self.user_root / "sample_plugin").exists())
        self.assertEqual(
            installer.get_transaction(transaction.transaction_id).state,
            "rolled_back",
        )

    def test_pending_content_digest_binds_manifest_and_files_to_import(self):
        transaction = self.installer.import_package(self._write_package())
        pending_plugin = (
            self.transaction_root
            / "pending"
            / transaction.transaction_id
            / "plugin.py"
        )
        pending_plugin.write_bytes(b"tampered after import\n")

        with self.assertRaises(PluginInstallerError) as changed:
            self.installer.apply_pending(transaction.transaction_id)

        self.assertEqual(changed.exception.code, "PENDING_CONTENT_CHANGED")
        self.assertFalse((self.user_root / "sample_plugin").exists())
        self.assertEqual(
            self.installer.get_transaction(transaction.transaction_id).state,
            "rolled_back",
        )

    def test_corrupt_metadata_blocks_new_transactions_and_cleans_new_staging(self):
        corrupt_id = "b" * 32
        metadata_path = (
            self.transaction_root / "transactions" / f"{corrupt_id}.json"
        )
        metadata_path.write_text("{}", encoding="utf-8")

        with self.assertRaises(PluginInstallerError) as corrupt:
            self.installer.import_package(self._write_package())

        self.assertEqual(corrupt.exception.code, "TRANSACTION_CORRUPT")
        self.assertEqual(list((self.transaction_root / "pending").iterdir()), [])

    def test_recovery_removes_orphan_staging_and_pending_cancel_is_clean(self):
        orphan = self.transaction_root / "pending" / "orphan-stage"
        orphan.mkdir()
        (orphan / "partial.txt").write_text("partial", encoding="utf-8")

        self.assertEqual(self.installer.recover_transactions(), [])
        self.assertFalse(orphan.exists())

        transaction = self.installer.import_package(self._write_package())
        pending = self.transaction_root / "pending" / transaction.transaction_id
        self.assertTrue(pending.is_dir())

        rolled_back = self.installer.rollback(transaction.transaction_id)

        self.assertEqual(rolled_back.state, "rolled_back")
        self.assertFalse(pending.exists())

    def test_recovery_normalizes_pending_enumeration_errors(self):
        with patch.object(
            Path,
            "iterdir",
            side_effect=OSError(errno.EIO, "pending directory cannot be read"),
        ):
            with self.assertRaises(PluginInstallerError) as caught:
                self.installer.recover_transactions()

        self.assertEqual(caught.exception.code, "TRANSACTION_IO_ERROR")
        self.assertIsNone(caught.exception.transaction_id)

    def test_recovery_normalizes_locked_orphan_cleanup_and_stops_recovery(self):
        transaction = self.installer.import_package(self._write_package())
        applying = self._rewrite_transaction(
            transaction,
            state="applying",
            had_previous=False,
        )
        orphan = self.transaction_root / "pending" / "orphan-stage"
        orphan.mkdir()
        (orphan / "partial.txt").write_text("partial", encoding="utf-8")

        with patch(
            "core.plugin_system.plugin_installer.shutil.rmtree",
            side_effect=PermissionError(errno.EACCES, "orphan is locked"),
        ):
            with self.assertRaises(PluginInstallerError) as caught:
                self.installer.recover_transactions()

        self.assertEqual(caught.exception.code, "FILE_LOCKED")
        self.assertIsNone(caught.exception.transaction_id)
        self.assertTrue(orphan.is_dir())
        self.assertEqual(
            self.installer.get_transaction(applying.transaction_id).state,
            "applying",
        )
        self.assertFalse((self.user_root / "sample_plugin").exists())

    def test_transaction_session_is_reentrant_for_decorated_operations(self):
        acquire = self.installer._acquire_transaction_lock
        release = self.installer._release_transaction_lock
        with patch.object(
            self.installer,
            "_acquire_transaction_lock",
            wraps=acquire,
        ) as acquire_lock, patch.object(
            self.installer,
            "_release_transaction_lock",
            wraps=release,
        ) as release_lock:
            with self.installer.transaction_session():
                self.assertEqual(self.installer.recover_transactions(), [])
                transaction = self.installer.stage_uninstall("missing_plugin")
                self.assertEqual(
                    self.installer.get_transaction(transaction.transaction_id),
                    transaction,
                )

            self.assertEqual(acquire_lock.call_count, 1)
            self.assertEqual(release_lock.call_count, 1)
            acquire_lock.reset_mock()
            release_lock.reset_mock()

            nested = self.installer.uninstall("nested_missing_plugin")

            self.assertEqual(nested.state, "applied")
            self.assertEqual(acquire_lock.call_count, 1)
            self.assertEqual(release_lock.call_count, 1)

        self.installer.transaction_lock_path.unlink()
        self.assertFalse(self.installer.transaction_lock_path.exists())

    def test_transaction_lock_reports_real_subprocess_contention(self):
        probe_script = "\n".join(
            (
                "import sys",
                "from core.plugin_system.plugin_installer import "
                "PluginInstaller, PluginInstallerError",
                "installer = PluginInstaller(sys.argv[1], sys.argv[2])",
                "try:",
                "    installer.list_transactions()",
                "except PluginInstallerError as error:",
                "    print(error.code)",
                "    raise SystemExit(0 if error.code == 'INSTALLER_BUSY' else 2)",
                "print('ACQUIRED')",
            )
        )

        def run_probe():
            return subprocess.run(
                [
                    sys.executable,
                    "-c",
                    probe_script,
                    str(self.user_root),
                    str(self.transaction_root),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        with self.installer.transaction_session():
            blocked = run_probe()

        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        self.assertEqual(blocked.stdout.strip(), "INSTALLER_BUSY")

        acquired = run_probe()
        self.assertEqual(acquired.returncode, 0, acquired.stderr)
        self.assertEqual(acquired.stdout.strip(), "ACQUIRED")

    def test_transaction_lock_rejects_unsafe_reparse_metadata(self):
        self.installer.transaction_lock_path.write_bytes(b"\0")
        with patch.object(
            self.installer,
            "_lock_stat_is_unsafe",
            return_value=True,
        ):
            with self.assertRaises(PluginInstallerError) as unsafe:
                self.installer.list_transactions()

        self.assertEqual(unsafe.exception.code, "UNSAFE_TRANSACTION_LOCK")

        self.installer.transaction_lock_path = self.root / "outside.lock"
        with self.assertRaises(PluginInstallerError) as escaped:
            self.installer.list_transactions()
        self.assertEqual(escaped.exception.code, "UNSAFE_TRANSACTION_LOCK")

    def test_transaction_lock_open_errors_are_normalized(self):
        with patch(
            "core.plugin_system.plugin_installer.os.open",
            side_effect=OSError(errno.EIO, "lock storage unavailable"),
        ):
            with self.assertRaises(PluginInstallerError) as caught:
                self.installer.list_transactions()

        self.assertEqual(caught.exception.code, "TRANSACTION_IO_ERROR")


if __name__ == "__main__":
    unittest.main()
