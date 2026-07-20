import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.plugin_system.event_bus import EventBus
from core.plugin_system.plugin_manager import PluginManager


def _write_plugin(root: Path, plugin_id: str, version: str):
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text("class Plugin: pass\n", encoding="utf-8")
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "name": "Sample Plugin",
                "version": version,
                "entry": "plugin.py",
                "class": "Plugin",
            }
        ),
        encoding="utf-8",
    )


def _write_v2_plugin(
    root: Path,
    plugin_id: str,
    version: str,
    *,
    plugins=None,
):
    plugin_dir = root / plugin_id
    plugin_dir.mkdir(parents=True)
    source = "class Plugin: pass\n"
    (plugin_dir / "plugin.py").write_text(source, encoding="utf-8")
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 2,
                "id": plugin_id,
                "name": plugin_id,
                "version": version,
                "entry": "plugin.py",
                "class": "Plugin",
                "api_version": "1.0",
                "compatibility": {
                    "app": ">=1",
                    "python_abi": "cp311",
                    "platform": "win_amd64",
                },
                "dependencies": {
                    "host": [],
                    "python": [],
                    "plugins": plugins or {},
                },
                "files": {
                    "plugin.py": hashlib.sha256(
                        (plugin_dir / "plugin.py").read_bytes()
                    ).hexdigest()
                },
                "native_modules": [],
                "requires_restart": False,
                "ui": {"type": "native"},
            }
        ),
        encoding="utf-8",
    )


class PluginStatusTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.bundled = self.root / "bundled"
        self.user = self.root / "user"
        self.bundled.mkdir()
        self.user.mkdir()
        self.manager = PluginManager(
            [str(self.bundled), str(self.user)],
            EventBus(),
            user_plugins_dir=str(self.user),
            transaction_root=str(self.root / "transactions"),
        )

    def _write_package(self, version="2.0.0", *, plugin_id="sample_plugin", plugins=None):
        package = self.root / f"{plugin_id}-{version}.atplugin"
        plugin_source = "class Plugin: pass\n"
        with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "manifest_version": 2,
                        "id": plugin_id,
                        "name": "Sample Plugin",
                        "version": version,
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
                            "python": [],
                            "plugins": plugins or {},
                        },
                        "ui": {"type": "native"},
                        "native_modules": [],
                        "files": {
                            "plugin.py": hashlib.sha256(
                                plugin_source.encode("utf-8")
                            ).hexdigest()
                        },
                        "requires_restart": False,
                    }
                ),
            )
            archive.writestr("plugin.py", plugin_source)
        return package

    def test_status_exposes_source_version_and_user_actions(self):
        _write_plugin(self.bundled, "sample_plugin", "1.0.0")
        _write_plugin(self.user, "sample_plugin", "1.5.0")
        self.manager.discover_plugins()

        status = self.manager.get_plugin_status("sample_plugin")

        self.assertEqual(status.source, "user")
        self.assertEqual(status.selected_version, "1.5.0")
        self.assertTrue(status.user_present)
        self.assertEqual(status.user_version, "1.5.0")
        self.assertTrue(status.can_uninstall)

    def test_corrupt_user_manifest_remains_visible_and_can_be_uninstalled(self):
        _write_plugin(self.bundled, "sample_plugin", "1.0.0")
        _write_plugin(self.user, "sample_plugin", "1.5.0")
        (self.user / "sample_plugin" / "manifest.json").write_text(
            "{not-json", encoding="utf-8"
        )
        self.manager.discover_plugins()

        status = self.manager.get_plugin_status("sample_plugin")

        self.assertEqual(status.source, "bundled")
        self.assertTrue(status.user_present)
        self.assertIsNone(status.user_version)
        self.assertTrue(status.can_uninstall)

        queued, _ = self.manager.queue_uninstall_plugin("sample_plugin")
        self.assertTrue(queued)
        pending = self.manager.get_plugin_status("sample_plugin")
        self.assertEqual(pending.transaction.operation, "uninstall")
        self.assertEqual(pending.transaction.state, "pending")
        self.assertFalse(pending.can_uninstall)

        self.manager.prepare_pending_updates()
        self.manager.discover_plugins()
        restored = self.manager.get_plugin_status("sample_plugin")
        self.assertEqual(restored.source, "bundled")
        self.assertEqual(restored.selected_version, "1.0.0")
        self.assertFalse(restored.user_present)
        self.assertFalse(restored.can_uninstall)

    def test_corrupt_user_only_plugin_is_still_listed_for_uninstall(self):
        _write_plugin(self.user, "broken_only", "1.0.0")
        (self.user / "broken_only" / "manifest.json").write_text(
            "{not-json", encoding="utf-8"
        )
        self.manager.discover_plugins()

        status = self.manager.get_plugin_status("broken_only")

        self.assertIsNotNone(status)
        self.assertEqual(status.source, "not-installed")
        self.assertTrue(status.user_present)
        self.assertIsNone(status.user_version)
        self.assertTrue(status.can_uninstall)

    def test_pending_install_is_visible_and_can_be_cancelled(self):
        _write_plugin(self.bundled, "sample_plugin", "1.0.0")
        self.manager.discover_plugins()
        self.assertTrue(self.manager.install_plugin(str(self._write_package()))[0])

        pending = self.manager.get_plugin_status("sample_plugin")

        self.assertEqual(pending.transaction.state, "pending")
        self.assertTrue(pending.restart_required)
        cancelled, _ = self.manager.cancel_pending_plugin_change("sample_plugin")
        self.assertTrue(cancelled)
        self.assertIsNone(
            self.manager.get_plugin_status("sample_plugin").transaction
        )

    def test_missing_required_plugin_rejects_import_before_transaction(self):
        package = self._write_package(
            plugin_id="dependent",
            plugins={"provider": ">=1"},
        )

        success, message = self.manager.install_plugin(str(package))

        self.assertFalse(success)
        self.assertIn("PLUGIN_DEPENDENCY_MISSING", message)
        self.assertEqual(self.manager.installer.list_transactions(), [])

    def test_different_plugins_can_queue_before_one_restart(self):
        first = self._write_package(plugin_id="first_plugin")
        second = self._write_package(plugin_id="second_plugin")

        self.assertTrue(self.manager.install_plugin(str(first))[0])
        success, message = self.manager.install_plugin(str(second))

        self.assertTrue(success)
        self.assertIn("Restart Agile Tiles once", message)
        self.assertEqual(
            {item.plugin_id for item in self.manager.installer.list_transactions()},
            {"first_plugin", "second_plugin"},
        )

        applied = self.manager.prepare_pending_updates()
        self.manager.discover_plugins()

        self.assertEqual({item.plugin_id for item in applied}, {"first_plugin", "second_plugin"})
        self.assertIn("first_plugin", self.manager.get_all_manifests())
        self.assertIn("second_plugin", self.manager.get_all_manifests())

    def test_same_plugin_still_allows_only_one_pending_change(self):
        first = self._write_package(version="2.0.0")
        second = self._write_package(version="3.0.0")

        self.assertTrue(self.manager.install_plugin(str(first))[0])
        success, message = self.manager.install_plugin(str(second))

        self.assertFalse(success)
        self.assertIn("PLUGIN_TRANSACTION_PENDING", message)
        self.assertEqual(len(self.manager.installer.list_transactions()), 1)

    def test_different_plugins_can_queue_uninstall_before_one_restart(self):
        _write_plugin(self.user, "first_plugin", "1.0.0")
        _write_plugin(self.user, "second_plugin", "1.0.0")
        self.manager.discover_plugins()

        self.assertTrue(self.manager.queue_uninstall_plugin("first_plugin")[0])
        success, message = self.manager.queue_uninstall_plugin("second_plugin")

        self.assertTrue(success)
        self.assertIn("Restart once", message)
        self.assertEqual(
            {
                item.plugin_id
                for item in self.manager.installer.list_transactions(
                    states={"pending"}
                )
            },
            {"first_plugin", "second_plugin"},
        )

        applied = self.manager.prepare_pending_updates()
        self.manager.discover_plugins()

        self.assertEqual(
            {item.plugin_id for item in applied},
            {"first_plugin", "second_plugin"},
        )
        self.assertIsNone(self.manager.get_plugin_status("first_plugin"))
        self.assertIsNone(self.manager.get_plugin_status("second_plugin"))

    def test_completed_uninstall_without_fallback_has_no_status_tombstone(self):
        install = self.manager.installer.import_package(self._write_package())
        self.manager.installer.apply_pending(install.transaction_id)
        self.manager.discover_plugins()
        self.assertIsNotNone(self.manager.get_plugin_status("sample_plugin"))

        uninstall = self.manager.installer.stage_uninstall("sample_plugin")
        self.manager.installer.apply_pending(uninstall.transaction_id)
        self.manager.discover_plugins()

        self.assertIsNone(self.manager.get_plugin_status("sample_plugin"))
        self.assertEqual(
            len(self.manager.installer.list_transactions(plugin_id="sample_plugin")),
            2,
        )

    def test_bundled_only_uninstall_is_rejected_and_applied_update_can_queue_rollback(self):
        _write_plugin(self.bundled, "sample_plugin", "1.0.0")
        self.manager.discover_plugins()

        success, message = self.manager.queue_uninstall_plugin("sample_plugin")
        self.assertFalse(success)
        self.assertIn("No user-installed", message)

        self.assertTrue(self.manager.install_plugin(str(self._write_package()))[0])
        self.manager.prepare_pending_updates()
        self.manager.discover_plugins()

        status = self.manager.get_plugin_status("sample_plugin")
        self.assertTrue(status.can_rollback)
        queued, _ = self.manager.queue_rollback_plugin("sample_plugin")
        self.assertTrue(queued)
        self.assertEqual(
            self.manager.get_plugin_status("sample_plugin").transaction.state,
            "rollback_pending",
        )

    def test_uninstall_rejects_incompatible_bundled_provider_fallback(self):
        _write_v2_plugin(self.bundled, "provider", "1.0.0")
        _write_v2_plugin(self.user, "provider", "2.0.0")
        _write_v2_plugin(
            self.bundled,
            "consumer",
            "1.0.0",
            plugins={"provider": ">=2"},
        )
        self.manager.discover_plugins()

        success, message = self.manager.queue_uninstall_plugin("provider")

        self.assertFalse(success)
        self.assertIn("PLUGIN_DEPENDENTS_BLOCKED", message)
        self.assertFalse(self.manager.get_plugin_status("provider").can_uninstall)

    def test_uninstall_allows_compatible_bundled_provider_fallback(self):
        _write_v2_plugin(self.bundled, "provider", "1.0.0")
        _write_v2_plugin(self.user, "provider", "2.0.0")
        _write_v2_plugin(
            self.bundled,
            "consumer",
            "1.0.0",
            plugins={"provider": ">=1"},
        )
        self.manager.discover_plugins()

        success, _ = self.manager.queue_uninstall_plugin("provider")

        self.assertTrue(success)
        transaction = self.manager.get_plugin_status("provider").transaction
        self.assertEqual(
            (transaction.operation, transaction.state),
            ("uninstall", "pending"),
        )

    def test_provider_with_enabled_dependents_uses_reinstall_instead_of_rollback(self):
        _write_v2_plugin(self.bundled, "provider", "1.0.0")
        _write_v2_plugin(
            self.bundled,
            "consumer",
            "1.0.0",
            plugins={"provider": ">=1"},
        )
        self.manager.discover_plugins()
        self.assertTrue(
            self.manager.install_plugin(
                str(self._write_package(version="2.0.0", plugin_id="provider"))
            )[0]
        )
        self.manager.prepare_pending_updates()
        self.manager.discover_plugins()

        status = self.manager.get_plugin_status("provider")
        success, message = self.manager.queue_rollback_plugin("provider")

        self.assertFalse(status.can_rollback)
        self.assertEqual(status.blocking_dependents, ("consumer",))
        self.assertFalse(success)
        self.assertIn("PLUGIN_DEPENDENTS_BLOCKED", message)


if __name__ == "__main__":
    unittest.main()
