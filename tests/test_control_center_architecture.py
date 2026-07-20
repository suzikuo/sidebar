import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ControlCenterArchitectureTest(unittest.TestCase):
    def test_tray_is_the_only_new_control_center_entry(self):
        main = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        sidebar = (PROJECT_ROOT / "core" / "window_system" / "sidebar.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('QAction("控制中心"', main)
        self.assertIn("def open_control_center", main)
        self.assertNotIn("control-center", sidebar)

    def test_control_center_assets_are_built_into_the_ui_tree(self):
        vite = (PROJECT_ROOT / "front" / "vite.config.ts").read_text(encoding="utf-8")
        spec = (PROJECT_ROOT / "AgileTiles.spec").read_text(encoding="utf-8")
        index = PROJECT_ROOT / "ui" / "control_center" / "web" / "index.html"

        self.assertIn("../ui/control_center/web", vite)
        self.assertIn("source_tree('ui')", spec)
        self.assertTrue(index.is_file())
        self.assertIn("qtwebchannel/qwebchannel.js", index.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
