import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from plugins.gateway_manager.views import GatewaySidebarWidget


class GatewaySidebarWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_status_indicator_has_a_fixed_navigation_cell_footprint(self):
        widget = GatewaySidebarWidget()
        widget.set_orientation("top")
        widget.set_count(12)
        widget.show()
        self.app.processEvents()

        self.assertEqual(widget.minimumSize().width(), 40)
        self.assertEqual(widget.minimumSize().height(), 40)
        self.assertEqual(widget.maximumSize().width(), 40)
        self.assertEqual(widget.maximumSize().height(), 40)
        self.assertLessEqual(widget.icon.geometry().right(), widget.rect().right())
        self.assertLessEqual(widget.statusDot.geometry().right(), widget.rect().right())
        self.assertIn("12 gateway(s) running", widget.toolTip())

        widget.close()


if __name__ == "__main__":
    unittest.main()
