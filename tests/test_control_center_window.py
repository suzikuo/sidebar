import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QWidget

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
            store.close()
            self.app.processEvents()

    def test_close_releases_web_host_and_reopen_builds_a_new_one(self):
        class FakeWebHost(QWidget):
            load_failed = Signal(str)

            def __init__(self):
                super().__init__()
                self.bridge = SimpleNamespace(publish_event=lambda *_: None)
                self.disposed = False

            def load(self):
                pass

            def dispose(self):
                self.disposed = True

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "index.html").write_text("<html></html>", encoding="utf-8")
            store = StateStore(str(root / "state.json"), save_delay_seconds=60)
            hosts = []

            def create_host(*_args, **_kwargs):
                host = FakeWebHost()
                hosts.append(host)
                return host

            with patch(
                "core.window_system.control_center.create_web_plugin_view",
                side_effect=create_host,
            ):
                window = ControlCenterWindow(ApiRegistry(), store, root)
                first = window._web_host
                window.show_center()
                self.app.processEvents()

                window.close()
                self.app.processEvents()
                self.assertTrue(first.disposed)
                self.assertIsNone(window._web_host)

                window.show_center()
                self.app.processEvents()
                self.assertEqual(len(hosts), 2)
                self.assertIsNot(window._web_host, first)

                window.force_close()
                store.close()
                self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
