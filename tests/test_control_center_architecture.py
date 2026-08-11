import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ControlCenterArchitectureTest(unittest.TestCase):
    def test_tray_and_settings_reuse_application_control_center_entry(self):
        application = (PROJECT_ROOT / "app" / "application.py").read_text(
            encoding="utf-8"
        )
        settings = (
            PROJECT_ROOT / "core" / "settings" / "fluent_settings_card.py"
        ).read_text(encoding="utf-8")
        sidebar = (PROJECT_ROOT / "core" / "window_system" / "sidebar.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('QAction("控制中心"', application)
        self.assertIn("def open_control_center", application)
        self.assertIn("open_control_center_requested = Signal()", settings)
        self.assertIn(
            "control_center_request.connect(self.open_control_center)",
            application,
        )
        self.assertNotIn("control-center", sidebar)

    def test_control_center_assets_are_built_into_the_ui_tree(self):
        vite = (PROJECT_ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")
        spec = (PROJECT_ROOT / "AgileTiles.spec").read_text(encoding="utf-8")
        index = PROJECT_ROOT / "resources" / "web" / "control-center" / "index.html"

        self.assertIn("../resources/web/control-center", vite)
        self.assertIn("source_tree('resources')", spec)
        self.assertTrue(index.is_file())
        index_text = index.read_text(encoding="utf-8")
        self.assertIn("connect-src 'none'", index_text)
        self.assertNotIn("WebSocket", index_text)
        self.assertIn("<script>", index_text)
        self.assertNotIn('type="module"', index_text)
        self.assertNotIn("qtwebchannel/qwebchannel.js", index_text)


if __name__ == "__main__":
    unittest.main()
