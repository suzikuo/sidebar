import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.data_layer.json_store import load_json, save_json_atomic


class JsonStoreTest(unittest.TestCase):
    def test_atomic_save_skips_unchanged_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            value = {"name": "Agile Tiles", "items": [1, 2, 3]}

            self.assertTrue(save_json_atomic(path, value))
            first_timestamp = path.stat().st_mtime_ns
            with patch("core.data_layer.json_store.os.replace") as replace:
                self.assertFalse(save_json_atomic(path, value))

            replace.assert_not_called()
            self.assertEqual(path.stat().st_mtime_ns, first_timestamp)
            self.assertEqual(load_json(path, {}), value)


if __name__ == "__main__":
    unittest.main()
