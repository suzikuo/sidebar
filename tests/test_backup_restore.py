import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from plugins.backup_restore.models import normalize_profile
from plugins.backup_restore.service import BackupArchiveService


class BackupArchiveServiceTest(unittest.TestCase):
    def test_archive_round_trip_restores_explicit_files_and_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "one.txt").write_text("one", encoding="utf-8")
            profile = normalize_profile(
                {
                    "id": "profile1",
                    "name": "Daily",
                    "sources": [str(source)],
                    "destination": str(root / "backups"),
                    "retention": 2,
                }
            )
            service = BackupArchiveService()

            created = service.create(profile, {"sample": {"value": 1}})
            restored = service.restore(created["path"], root / "restore")

            self.assertEqual(restored["manifest"]["pluginSnapshots"]["sample"], {"value": 1})
            restored_files = list((root / "restore" / "files").rglob("one.txt"))
            self.assertEqual(len(restored_files), 1)
            self.assertEqual(restored_files[0].read_text(encoding="utf-8"), "one")

    def test_restore_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "unsafe.atbackup"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps({"schemaVersion": 1, "pluginSnapshots": {}}),
                )
                archive.writestr("../outside.txt", "unsafe")

            with self.assertRaises(ValueError):
                BackupArchiveService().restore(archive_path, root / "restore")
            self.assertFalse((root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
