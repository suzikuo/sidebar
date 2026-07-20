import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from core.api_gateway import ApiRegistry
from core.state_store import StateStore
from core.window_system.control_center import ControlCenterWindow


class ControlCenterWindowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_close_hides_and_force_close_persists_geometry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = StateStore(str(root / "state.json"))
            store.set_system_state(
                ControlCenterWindow.STATE_KEY,
                {"x": "bad", "y": None, "width": "invalid", "height": []},
            )
            window = ControlCenterWindow(ApiRegistry(), store, root / "missing-assets")
            window.resize(920, 680)
            window.show_center()
            self.app.processEvents()

            window.close()
            self.app.processEvents()

            self.assertFalse(window.isVisible())
            saved = store.get_system_state(ControlCenterWindow.STATE_KEY)
            self.assertEqual(saved["width"], 920)
            self.assertEqual(saved["height"], 680)

            window.force_close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
