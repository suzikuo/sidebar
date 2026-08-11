import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from core.state_store import StateStore
from core.ui_kernel.design_tokens import DesignTokens
from core.ui_kernel.theme_engine import ThemeEngine
from core.window_system.main_window import DetailWindow


class DetailWindowLifecycleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, temp_dir):
        store = StateStore(
            str(Path(temp_dir) / "state.json"),
            save_delay_seconds=60,
        )
        window = DetailWindow(ThemeEngine(DesignTokens()), store)
        return window, store

    def test_plugin_widget_is_created_once_on_first_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window, store = self._window(temp_dir)
            try:
                created = []

                def create_widget():
                    created.append(True)
                    return QWidget()

                window.add_plugin_interface_factory("sample", create_widget, "Sample")
                self.assertEqual(created, [])
                self.assertNotIn("sample", window.plugin_widgets)

                window.show_plugin("sample")
                self.app.processEvents()
                self.assertEqual(created, [True])

                window.hide_content()
                window.show_plugin("sample")
                self.app.processEvents()
                self.assertEqual(created, [True])

                window.remove_plugin_interface("sample")
                self.assertNotIn("sample", window.plugin_factories)
                self.assertNotIn("sample", window.plugin_widgets)
            finally:
                window.force_close()
                store.close()

    def test_factory_failure_emits_error_and_installs_placeholder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            window, store = self._window(temp_dir)
            try:
                failures = []
                window.plugin_view_failed.connect(
                    lambda plugin_id, message: failures.append((plugin_id, message))
                )

                def fail():
                    raise RuntimeError("view failed")

                window.add_plugin_interface_factory("broken", fail, "Broken")
                window.show_plugin("broken")
                self.app.processEvents()

                self.assertEqual(failures, [("broken", "view failed")])
                self.assertIn("broken", window.plugin_widgets)
                self.assertIn("view failed", window.plugin_widgets["broken"].text())
            finally:
                window.force_close()
                store.close()


if __name__ == "__main__":
    unittest.main()
