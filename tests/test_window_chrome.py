import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.state_store import StateStore
from core.settings.fluent_settings_card import FluentSettingsCard
from core.settings.settings_manager import SettingsManager
from core.ui_kernel.design_tokens import DesignTokens
from core.ui_kernel.theme_engine import ThemeEngine
from core.window_system.main_window import DetailWindow
from core.window_system.sidebar import SidebarWindow


class ShellWindowChromeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_primary_shell_windows_remain_frameless_tools(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_store = StateStore(str(Path(temp_dir) / "state.json"))
            sidebar = SidebarWindow(state_store)
            detail = DetailWindow(ThemeEngine(DesignTokens()), state_store)

            for window in (sidebar, detail):
                with self.subTest(window=type(window).__name__):
                    self.assertTrue(window.windowFlags() & Qt.FramelessWindowHint)
                    self.assertTrue(window.windowFlags() & Qt.Tool)

            self.assertTrue(detail.titleBar.minBtn.isHidden())
            self.assertTrue(detail.titleBar.maxBtn.isHidden())
            self.assertTrue(detail.titleBar.closeBtn.isHidden())

            detail.force_close()
            sidebar.close()
            self.app.processEvents()

    def test_production_settings_surface_uses_native_fluent_components(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_store = StateStore(str(Path(temp_dir) / "state.json"))
            manager = SettingsManager(ThemeEngine(DesignTokens()), state_store)

            settings = manager.get_settings_widget()

            self.assertIsInstance(settings, FluentSettingsCard)
            self.assertEqual(settings.objectName(), "FluentSettingsCard")
            settings.close()
            self.app.processEvents()

    def test_global_settings_frontend_is_not_collected_by_pyinstaller(self):
        project_root = Path(__file__).resolve().parents[1]
        spec = (project_root / "AgileTiles.spec").read_text(encoding="utf-8")
        main = (project_root / "main.py").read_text(encoding="utf-8")

        self.assertNotIn("front/dist/desktop", spec)
        self.assertNotIn("SettingsInterface", main)


if __name__ == "__main__":
    unittest.main()
