import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.web_ui.runtime import (
    detect_webview2_runtime,
    ensure_native_qwebview_available,
    missing_runtime_message,
)


class WebView2RuntimeTest(unittest.TestCase):
    def test_runtime_probe_is_read_only_and_selects_highest_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Application"
            low = root / "125.0.1.0"
            high = root / "126.0.2.0"
            low.mkdir(parents=True)
            high.mkdir()
            (low / "msedgewebview2.exe").write_bytes(b"")
            (high / "msedgewebview2.exe").write_bytes(b"")

            with patch("core.web_ui.runtime.sys.platform", "win32"), patch(
                "core.web_ui.runtime._runtime_roots", return_value=(root,)
            ):
                result = detect_webview2_runtime()

        self.assertTrue(result["available"])
        self.assertEqual(result["version"], "126.0.2.0")
        self.assertTrue(str(result["path"]).endswith("126.0.2.0\\msedgewebview2.exe"))

    def test_missing_runtime_message_is_actionable(self):
        self.assertIn("WebView2 Runtime", missing_runtime_message())
        self.assertIn("Evergreen Runtime", missing_runtime_message())

    def test_old_pyside_environment_has_actionable_error(self):
        with patch(
            "core.web_ui.runtime.import_module",
            return_value=SimpleNamespace(),
        ), patch("core.web_ui.runtime.version", return_value="6.10.2"):
            with self.assertRaisesRegex(RuntimeError, "6.11.1.*6.10.2"):
                ensure_native_qwebview_available()


if __name__ == "__main__":
    unittest.main()
