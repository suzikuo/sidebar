import json
import tempfile
import unittest
from pathlib import Path

from core.display_scaling import (
    apply_ui_scale,
    configure_ui_scale,
    normalize_ui_scale,
    read_ui_scale_setting,
)


class DisplayScalingTest(unittest.TestCase):
    def test_normalize_ui_scale_accepts_supported_values(self):
        self.assertEqual(normalize_ui_scale("150"), "150")
        self.assertEqual(normalize_ui_scale(" AUTO "), "auto")
        self.assertEqual(normalize_ui_scale("300"), "auto")
        self.assertEqual(normalize_ui_scale(None), "auto")

    def test_read_ui_scale_setting_reads_nested_appearance_value(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps({"settings": {"appearance": {"ui_scale": "175"}}}),
                encoding="utf-8",
            )

            self.assertEqual(read_ui_scale_setting(state_path), "175")

    def test_read_ui_scale_setting_uses_backup_when_primary_is_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text("invalid json", encoding="utf-8")
            backup_path = Path(directory) / "state.json.bak"
            backup_path.write_text(
                json.dumps({"settings": {"appearance": {"ui_scale": "125"}}}),
                encoding="utf-8",
            )

            self.assertEqual(read_ui_scale_setting(state_path), "125")

    def test_apply_ui_scale_sets_qt_environment_for_manual_scale(self):
        environ = {}

        self.assertEqual(apply_ui_scale("150", environ), "150")
        self.assertEqual(environ["QT_SCALE_FACTOR"], "1.5")
        self.assertEqual(environ["QT_SCALE_FACTOR_ROUNDING_POLICY"], "PassThrough")
        self.assertEqual(environ["AGILE_TILES_MANAGED_QT_SCALE"], "150")

    def test_apply_auto_removes_scale_inherited_from_previous_app_restart(self):
        environ = {
            "QT_SCALE_FACTOR": "2",
            "QT_SCALE_FACTOR_ROUNDING_POLICY": "PassThrough",
            "AGILE_TILES_MANAGED_QT_SCALE": "200",
        }

        self.assertEqual(apply_ui_scale("auto", environ), "auto")
        self.assertNotIn("QT_SCALE_FACTOR", environ)
        self.assertNotIn("QT_SCALE_FACTOR_ROUNDING_POLICY", environ)
        self.assertNotIn("AGILE_TILES_MANAGED_QT_SCALE", environ)

    def test_apply_auto_preserves_user_managed_qt_scale(self):
        environ = {"QT_SCALE_FACTOR": "1.25"}

        apply_ui_scale("auto", environ)

        self.assertEqual(environ["QT_SCALE_FACTOR"], "1.25")

    def test_configure_ui_scale_reads_and_applies_saved_value(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(
                json.dumps({"settings": {"appearance": {"ui_scale": "200"}}}),
                encoding="utf-8",
            )
            environ = {}

            self.assertEqual(configure_ui_scale(state_path, environ), "200")
            self.assertEqual(environ["QT_SCALE_FACTOR"], "2")


if __name__ == "__main__":
    unittest.main()
