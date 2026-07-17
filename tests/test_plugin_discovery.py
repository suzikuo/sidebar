import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from core.data_layer.path_utils import PathManager
from core.plugin_system.event_bus import EventBus
from core.plugin_system.manifest_loader import ManifestLoader
from core.plugin_system.plugin_manifest import HostEnvironment
from core.plugin_system.plugin_manager import PluginManager
from tests.pe_test_utils import build_test_pe


def _write_plugin(
    root: Path,
    directory_name: str,
    plugin_id: str,
    version: str = "1.0.0",
    entry: str = "plugin.py",
    source: str | None = None,
) -> Path:
    plugin_dir = root / directory_name
    plugin_dir.mkdir(parents=True)
    entry_path = plugin_dir.joinpath(*entry.replace("\\", "/").split("/"))
    entry_path.parent.mkdir(parents=True, exist_ok=True)
    entry_path.write_text(
        source or "class Plugin:\n    pass\n",
        encoding="utf-8",
    )
    manifest = {
        "id": plugin_id,
        "name": plugin_id,
        "version": version,
        "entry": entry,
        "class": "Plugin",
    }
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return plugin_dir


def _write_v2_package(
    package_path: Path,
    *,
    plugin_id: str = "sample_plugin",
    version: str = "2.0.0",
    source: str = "class Plugin: pass\n",
    extra_files: dict[str, str | bytes] | None = None,
    native_modules: tuple[tuple[str, str, bytes], ...] = (),
) -> Path:
    package_files: dict[str, str | bytes] = {"plugin.py": source}
    package_files.update(extra_files or {})
    native_declarations = []
    for module_name, relative_path, content in native_modules:
        package_files[relative_path] = content
        native_declarations.append(
            {
                "module": module_name,
                "path": relative_path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )

    file_hashes = {}
    for relative_path, content in package_files.items():
        raw_content = content if isinstance(content, bytes) else content.encode("utf-8")
        file_hashes[relative_path] = hashlib.sha256(raw_content).hexdigest()

    manifest = {
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
        "dependencies": {"host": [], "python": []},
        "ui": {"type": "native"},
        "native_modules": native_declarations,
        "files": file_hashes,
        "requires_restart": bool(native_declarations),
    }
    with zipfile.ZipFile(package_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for relative_path, content in package_files.items():
            archive.writestr(relative_path, content)
    return package_path


class PathManagerPluginPathsTest(unittest.TestCase):
    def test_search_paths_are_bundled_then_writable_user_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            base_dir = temp_root / "app"
            app_data = temp_root / "appdata"
            bundled = base_dir / "plugins"
            internal = base_dir / "_internal" / "plugins"
            bundled.mkdir(parents=True)
            internal.mkdir(parents=True)

            with patch.object(PathManager, "get_base_dir", return_value=base_dir):
                with patch.object(
                    PathManager, "get_app_data_root", return_value=app_data
                ):
                    paths = PathManager.get_plugin_search_paths()

            self.assertEqual(paths, [bundled, internal, app_data / "user-plugins"])
            self.assertTrue(paths[-1].is_dir())

    def test_missing_bundled_roots_are_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "app"
            app_data = Path(tmp) / "appdata"

            with patch.object(PathManager, "get_base_dir", return_value=base_dir):
                with patch.object(
                    PathManager, "get_app_data_root", return_value=app_data
                ):
                    paths = PathManager.get_plugin_search_paths()

            self.assertEqual(paths, [app_data / "user-plugins"])
            self.assertFalse((base_dir / "plugins").exists())


class ManifestLoaderSecurityTest(unittest.TestCase):
    def test_accepts_safe_nested_python_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = _write_plugin(
                Path(tmp), "bookmarks", "bookmarks.card", entry="src/plugin.py"
            )

            manifest = ManifestLoader.load(str(plugin_dir))

            self.assertIsNotNone(manifest)
            self.assertEqual(manifest["id"], "bookmarks.card")

    def test_rejects_unsafe_plugin_ids(self):
        invalid_ids = ["../evil", "BadPlugin", "a..b", "a/b", "a" * 65]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, plugin_id in enumerate(invalid_ids):
                with self.subTest(plugin_id=plugin_id):
                    plugin_dir = _write_plugin(root, f"plugin-{index}", plugin_id)
                    self.assertIsNone(ManifestLoader.load(str(plugin_dir)))

    def test_rejects_unsafe_or_missing_entries(self):
        invalid_entries = [
            "../outside.py",
            "missing.py",
            "plugin.txt",
            "C:\\Windows\\system32\\evil.py",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "outside.py").write_text("pass\n", encoding="utf-8")
            for index, entry in enumerate(invalid_entries):
                with self.subTest(entry=entry):
                    plugin_dir = root / f"plugin-{index}"
                    plugin_dir.mkdir()
                    manifest = {
                        "id": f"plugin-{index}",
                        "name": "Plugin",
                        "version": "1.0.0",
                        "entry": entry,
                        "class": "Plugin",
                    }
                    (plugin_dir / "manifest.json").write_text(
                        json.dumps(manifest), encoding="utf-8"
                    )
                    if entry == "plugin.txt":
                        (plugin_dir / entry).write_text("pass\n", encoding="utf-8")

                    self.assertIsNone(ManifestLoader.load(str(plugin_dir)))

    def test_directory_loader_uses_shared_typed_core_validation(self):
        cases = (
            ("Not.Valid", "1.0.0", "1.0"),
            ("Plugin", "not a version", "1.0"),
            ("Plugin", "1.0.0", "1"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, (class_name, version, api_version) in enumerate(cases):
                plugin_dir = _write_plugin(root, f"plugin-{index}", f"plugin-{index}")
                manifest_path = plugin_dir / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["class"] = class_name
                manifest["version"] = version
                manifest["api_version"] = api_version
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                self.assertIsNone(ManifestLoader.load(str(plugin_dir)))


class PluginDiscoveryPriorityTest(unittest.TestCase):
    @staticmethod
    def _host(python_abi="cp311"):
        return HostEnvironment(
            app_version="1.0.0",
            api_version="1.0",
            python_abi=python_abi,
            platform_tag="win_amd64",
            host_packages={},
        )

    def test_user_source_overrides_bundled_sources_and_records_relationship(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            internal = root / "internal"
            user = root / "user"
            bundled_plugin = _write_plugin(bundled, "toolbox", "toolbox", "1.0.0")
            internal_plugin = _write_plugin(internal, "toolbox", "toolbox", "1.1.0")
            user_plugin = _write_plugin(user, "toolbox", "toolbox", "2.0.0")

            manager = PluginManager(
                [str(bundled), str(internal), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
            )
            manifests = manager.discover_plugins()

            self.assertEqual(manifests["toolbox"]["version"], "2.0.0")
            self.assertEqual(manager.get_plugin_source("toolbox")["kind"], "user")
            self.assertEqual(
                manager.get_plugin_source("toolbox")["path"], str(user_plugin.resolve())
            )
            self.assertEqual(
                [item["path"] for item in manager.get_plugin_overrides("toolbox")],
                [str(bundled_plugin.resolve()), str(internal_plugin.resolve())],
            )

            detached = manager.get_plugin_source("toolbox")
            detached["kind"] = "changed"
            self.assertEqual(manager.get_plugin_source("toolbox")["kind"], "user")

    def test_duplicate_id_in_one_root_uses_first_sorted_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "bundled"
            first = _write_plugin(source, "a-plugin", "duplicate", "1.0.0")
            _write_plugin(source, "z-plugin", "duplicate", "9.0.0")

            manager = PluginManager(
                [str(source)],
                EventBus(),
                user_plugins_dir=str(root / "user"),
            )
            manifests = manager.discover_plugins()

            self.assertEqual(manifests["duplicate"]["version"], "1.0.0")
            self.assertEqual(
                manager.get_plugin_source("duplicate")["path"], str(first.resolve())
            )

    def test_user_root_ignores_noncanonical_directory_for_same_plugin_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            _write_plugin(bundled, "sample", "sample", "0.9.0")
            _write_plugin(user, "a-old", "sample", "1.0.0")
            canonical = _write_plugin(user, "sample", "sample", "2.0.0")

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )

            manifests = manager.discover_plugins()

            self.assertEqual(manifests["sample"]["version"], "2.0.0")
            self.assertEqual(
                manager.get_plugin_source("sample")["path"],
                str(canonical.resolve()),
            )

    def test_incompatible_user_manifest_falls_back_to_bundled_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled_plugin = _write_plugin(bundled, "sample", "sample", "1.0.0")
            user_plugin = _write_plugin(user, "sample", "sample", "2.0.0")
            manifest_path = user_plugin / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.update(
                {
                    "manifest_version": 2,
                    "api_version": "1.0",
                    "compatibility": {
                        "app": ">=1.0.0,<2.0.0",
                        "python_abi": "cp312",
                        "platform": "win_amd64",
                    },
                    "dependencies": {"host": [], "python": []},
                    "ui": {"type": "native"},
                    "native_modules": [],
                    "files": {
                        "plugin.py": hashlib.sha256(
                            (user_plugin / "plugin.py").read_bytes()
                        ).hexdigest()
                    },
                    "requires_restart": True,
                }
            )
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
                host_environment=self._host(),
            )

            manifests = manager.discover_plugins()

            self.assertEqual(manifests["sample"]["version"], "1.0.0")
            self.assertEqual(
                manager.get_plugin_source("sample")["path"],
                str(bundled_plugin.resolve()),
            )
            self.assertEqual(
                manager.get_compatibility_errors()["sample"]["code"],
                "INCOMPATIBLE_PYTHON_ABI",
            )

    def test_incompatible_v2_package_is_rejected_before_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            user.mkdir()
            package = root / "sample.atplugin"
            plugin_source = "class Plugin: pass\n"
            manifest = {
                "manifest_version": 2,
                "id": "sample_plugin",
                "name": "Sample Plugin",
                "version": "2.0.0",
                "entry": "plugin.py",
                "class": "Plugin",
                "api_version": "1.0",
                "compatibility": {
                    "app": ">=1.0.0,<2.0.0",
                    "python_abi": "cp312",
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

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
                host_environment=self._host(),
            )

            success, message = manager.install_plugin(str(package))

            self.assertFalse(success)
            self.assertIn("INCOMPATIBLE_PYTHON_ABI", message)
            self.assertEqual(manager.installer.list_transactions(), [])

    def test_invalid_transaction_storage_does_not_block_bundled_plugins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            transaction_root = root / "transactions"
            transaction_root.write_text("not a directory", encoding="utf-8")
            _write_plugin(
                bundled,
                "healthy",
                "healthy",
                source=(
                    "class Plugin:\n"
                    "    def __init__(self, context):\n"
                    "        self.context = context\n"
                    "    def on_load(self):\n"
                    "        pass\n"
                    "    def on_unload(self):\n"
                    "        pass\n"
                ),
            )

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(transaction_root),
            )

            manager.discover_and_load()

            self.assertIsNotNone(manager.get_plugin("healthy"))
            self.assertIn("plugin-installer", manager.get_load_errors())
            success, message = manager.install_plugin(str(root / "missing.atplugin"))
            self.assertFalse(success)
            self.assertIn("installer unavailable", message.lower())
            manager.shutdown()

    def test_discovery_does_not_create_missing_bundled_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing-bundled"
            user = root / "user"
            user.mkdir()
            manager = PluginManager(
                [str(missing), str(user)], EventBus(), user_plugins_dir=str(user)
            )

            manager.discover_plugins()

            self.assertFalse(missing.exists())

    def test_standalone_pyd_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            user.mkdir()
            package = root / "native.pyd"
            package.write_bytes(b"placeholder")
            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )

            success, message = manager.install_plugin(str(package))

            self.assertFalse(success)
            self.assertIn("Standalone .pyd", message)
            self.assertFalse((user / "native_plugin").exists())
            self.assertFalse((bundled / "native_plugin").exists())

    def test_atplugin_rejects_legacy_v1_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            user.mkdir()
            package = root / "legacy.atplugin"
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "id": "legacy_plugin",
                            "name": "Legacy Plugin",
                            "version": "1.0.0",
                            "entry": "plugin.py",
                            "class": "Plugin",
                        }
                    ),
                )
                archive.writestr("plugin.py", "class Plugin: pass\n")
            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )

            success, message = manager.install_plugin(str(package))

            self.assertFalse(success)
            self.assertIn("MANIFEST_V2_REQUIRED", message)
            self.assertEqual(manager.installer.list_transactions(), [])

    def test_v2_atplugin_is_queued_then_applied_before_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            user.mkdir()
            _write_plugin(bundled, "sample", "sample_plugin", "1.0.0")
            package = root / "sample.atplugin"
            _write_v2_package(
                package,
                source=(
                    "from .version_info import VERSION\n"
                    "class Plugin:\n"
                    "    VERSION = VERSION\n"
                    "    def __init__(self, context): self.context = context\n"
                    "    def on_load(self): pass\n"
                    "    def on_unload(self): pass\n"
                ),
                extra_files={"version_info.py": "VERSION = '2.0.0'\n"},
            )

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )

            success, message = manager.install_plugin(str(package))

            self.assertTrue(success)
            self.assertIn("Restart", message)
            self.assertFalse((user / "sample_plugin").exists())

            results = manager.prepare_pending_updates()
            manager.discover_and_load()
            manifests = manager.get_all_manifests()

            self.assertEqual([item.state for item in results], ["applied"])
            self.assertEqual(manifests["sample_plugin"]["version"], "2.0.0")
            self.assertEqual(manager.get_plugin("sample_plugin").VERSION, "2.0.0")
            self.assertEqual(manager.get_plugin_source("sample_plugin")["kind"], "user")
            self.assertEqual(
                manager.get_plugin_overrides("sample_plugin")[0]["kind"],
                "bundled",
            )
            manager.shutdown()

    def test_failed_pure_python_update_rolls_back_and_loads_previous_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            previous = _write_plugin(
                user,
                "sample_plugin",
                "sample_plugin",
                "1.0.0",
                source=(
                    "class Plugin:\n"
                    "    VERSION = '1.0.0'\n"
                    "    def __init__(self, context): self.context = context\n"
                    "    def on_load(self): pass\n"
                    "    def on_unload(self): pass\n"
                ),
            )
            package = root / "sample.atplugin"
            _write_v2_package(
                package,
                source=(
                    "class Plugin:\n"
                    "    def __init__(self, context): self.context = context\n"
                    "    def on_load(self): raise RuntimeError('broken update')\n"
                    "    def on_unload(self): pass\n"
                ),
            )

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )
            success, _ = manager.install_plugin(str(package))
            self.assertTrue(success)

            manager.discover_and_load()

            plugin = manager.get_plugin("sample_plugin")
            self.assertIsNotNone(plugin)
            self.assertEqual(plugin.VERSION, "1.0.0")
            restored_manifest = json.loads(
                (previous / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(restored_manifest["version"], "1.0.0")
            self.assertEqual(
                manager.get_update_errors()["sample_plugin"]["rollback"],
                "completed",
            )
            transaction = manager.installer.list_transactions(
                plugin_id="sample_plugin"
            )[0]
            self.assertEqual(transaction.state, "rolled_back")
            manager.shutdown()

    def test_native_update_failure_queues_rollback_for_next_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            _write_plugin(
                user,
                "sample_plugin",
                "sample_plugin",
                "1.0.0",
                source=(
                    "class Plugin:\n"
                    "    VERSION = '1.0.0'\n"
                    "    def __init__(self, context): self.context = context\n"
                    "    def on_load(self): pass\n"
                    "    def on_unload(self): pass\n"
                ),
            )
            package = root / "sample.atplugin"
            _write_v2_package(
                package,
                source=(
                    "class Plugin:\n"
                    "    def __init__(self, context): self.context = context\n"
                    "    def on_load(self): raise RuntimeError('native failure')\n"
                    "    def on_unload(self): pass\n"
                ),
                native_modules=(
                    (
                        "sample.fast",
                        "sample/fast.cp311-win_amd64.pyd",
                        build_test_pe(),
                    ),
                ),
            )

            manager = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )
            self.assertTrue(manager.install_plugin(str(package))[0])

            manager.discover_and_load()

            pending = manager.installer.list_transactions(
                plugin_id="sample_plugin"
            )[0]
            self.assertEqual(pending.state, "rollback_pending")
            self.assertIsNone(manager.get_plugin("sample_plugin"))
            self.assertEqual(
                manager.get_update_errors()["sample_plugin"]["rollback"],
                "pending",
            )
            manager.refresh_plugin_state()
            self.assertIsNone(manager.get_plugin("sample_plugin"))
            manager.shutdown()

            restarted = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )
            restarted.discover_and_load()

            plugin = restarted.get_plugin("sample_plugin")
            self.assertIsNotNone(plugin)
            self.assertEqual(plugin.VERSION, "1.0.0")
            rolled_back = restarted.installer.list_transactions(
                plugin_id="sample_plugin"
            )[0]
            self.assertEqual(rolled_back.state, "rolled_back")
            restarted.shutdown()

    def test_crash_window_unverified_update_is_verified_on_next_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundled = root / "bundled"
            user = root / "user"
            bundled.mkdir()
            user.mkdir()
            package = root / "sample.atplugin"
            _write_v2_package(
                package,
                source=(
                    "class Plugin:\n"
                    "    def __init__(self, context): self.context = context\n"
                    "    def on_load(self): pass\n"
                    "    def on_unload(self): pass\n"
                ),
            )

            first = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )
            self.assertTrue(first.install_plugin(str(package))[0])
            applied = first.prepare_pending_updates()[0]
            self.assertFalse(applied.load_verified)

            restarted = PluginManager(
                [str(bundled), str(user)],
                EventBus(),
                user_plugins_dir=str(user),
                transaction_root=str(root / "transactions"),
            )
            restarted.discover_and_load()

            transaction = restarted.installer.list_transactions(
                plugin_id="sample_plugin"
            )[0]
            self.assertTrue(transaction.load_verified)
            self.assertIsNotNone(restarted.get_plugin("sample_plugin"))
            restarted.shutdown()


if __name__ == "__main__":
    unittest.main()
