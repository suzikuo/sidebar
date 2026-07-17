import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from core.state_store import StateStore


class StateStoreTest(unittest.TestCase):
    def test_save_preserves_mutable_get_contract_and_rotates_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            backup_path = Path(f"{state_path}.bak")
            store = StateStore(str(state_path))

            store.set("settings", {"appearance": {"theme": "dark"}})
            settings = store.get("settings")
            settings["appearance"]["theme"] = "light"
            store.save()

            reloaded = StateStore(str(state_path))
            backup = json.loads(backup_path.read_text(encoding="utf-8"))
            self.assertEqual(
                reloaded.get("settings")["appearance"]["theme"], "light"
            )
            self.assertEqual(backup["settings"]["appearance"]["theme"], "dark")

    def test_corrupt_primary_recovers_and_repairs_from_valid_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            backup_path = Path(f"{state_path}.bak")
            state_path.write_text("{broken", encoding="utf-8")
            backup_path.write_text(
                json.dumps({"system": {"visible": True}, "plugins": {}}),
                encoding="utf-8",
            )

            with patch("core.state_store.logger.error"), patch(
                "core.state_store.logger.warning"
            ):
                store = StateStore(str(state_path))

            self.assertTrue(store.get_system_state("visible"))
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8")),
                {"system": {"visible": True}, "plugins": {}},
            )
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    def test_invalid_primary_does_not_replace_existing_valid_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            backup_path = Path(f"{state_path}.bak")
            store = StateStore(str(state_path))
            store.set("version", 1)
            state_path.write_text("not-json", encoding="utf-8")

            with patch("core.state_store.logger.error"):
                store.set("version", 2)

            self.assertEqual(
                json.loads(backup_path.read_text(encoding="utf-8"))["version"], 1
            )
            self.assertEqual(
                json.loads(state_path.read_text(encoding="utf-8"))["version"], 2
            )

    def test_replace_failure_preserves_primary_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            store = StateStore(str(state_path))
            store.set("settings", {"value": 1})
            store.get("settings")["value"] = 2
            original_payload = state_path.read_bytes()
            real_replace = os.replace

            def fail_primary_replace(source, destination):
                if os.path.abspath(destination) == os.path.abspath(state_path):
                    raise OSError("simulated replace failure")
                return real_replace(source, destination)

            with patch(
                "core.state_store.os.replace", side_effect=fail_primary_replace
            ), patch("core.state_store.logger.error"):
                store.save()

            self.assertEqual(state_path.read_bytes(), original_payload)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    def test_failed_first_save_does_not_publish_uncommitted_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            backup_path = Path(f"{state_path}.bak")
            store = StateStore(str(state_path))

            with patch(
                "core.state_store.os.replace",
                side_effect=OSError("simulated replace failure"),
            ), patch("core.state_store.logger.error"):
                store.set("value", "not-committed")

            self.assertFalse(state_path.exists())
            self.assertFalse(backup_path.exists())
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])

    def test_concurrent_setters_leave_complete_valid_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            store = StateStore(str(state_path))

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    executor.submit(store.set_plugin_state, "sample", f"key-{i}", i)
                    for i in range(32)
                ]
                for future in futures:
                    future.result()

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                persisted["plugins"]["sample"],
                {f"key-{i}": i for i in range(32)},
            )

    def test_save_flushes_state_and_backup_to_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            store = StateStore(str(state_path))

            with patch("core.state_store.os.fsync", wraps=os.fsync) as fsync:
                store.set_system_state("ready", True)

            self.assertGreaterEqual(fsync.call_count, 2)

    def test_unserializable_change_does_not_damage_existing_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            store = StateStore(str(state_path))
            store.set("value", "valid")
            original_payload = state_path.read_bytes()

            with patch("core.state_store.logger.error"):
                store.set("value", object())

            self.assertEqual(state_path.read_bytes(), original_payload)
            self.assertEqual(list(Path(temp_dir).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
