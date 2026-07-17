import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from qfluentwidgets import FluentIcon, NavigationItemPosition

from core.window_system.horizontal_navigation import HorizontalNavigationInterface


def _wheel_event(*, pixel=(0, 0), angle=(0, 0)):
    return QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(*pixel),
        QPoint(*angle),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )


class HorizontalNavigationInterfaceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.navigation = HorizontalNavigationInterface()
        self.navigation.resize(260, 50)

    def tearDown(self):
        self.navigation.close()
        self.navigation.deleteLater()
        self.app.processEvents()

    def _add_scroll_items(self, count):
        return [
            self.navigation.addItem(
                f"plugin-{index}",
                FluentIcon.APPLICATION,
                f"Plugin {index}",
                position=NavigationItemPosition.SCROLL,
            )
            for index in range(count)
        ]

    def _show(self):
        self.navigation.show()
        self.app.processEvents()

    def test_fixed_regions_stay_visible_while_middle_region_scrolls(self):
        leading = self.navigation.addItem(
            "leading",
            FluentIcon.HOME,
            "Leading",
            position=NavigationItemPosition.TOP,
        )
        plugins = self._add_scroll_items(12)
        settings = self.navigation.addItem(
            "settings",
            FluentIcon.SETTING,
            "Settings",
            position=NavigationItemPosition.BOTTOM,
        )
        self._show()

        bar = self.navigation.scrollArea.horizontalScrollBar()
        self.assertEqual(self.navigation.width(), 260)
        self.assertEqual(self.navigation.height(), 50)
        self.assertGreater(bar.maximum(), 0)
        self.assertIs(leading.parent(), self.navigation)
        self.assertIs(plugins[0].parent(), self.navigation.scrollWidget)
        self.assertIs(settings.parent(), self.navigation)

        leading_x = leading.mapTo(self.navigation, QPoint()).x()
        settings_x = settings.mapTo(self.navigation, QPoint()).x()
        first_plugin_x = plugins[0].mapTo(self.navigation, QPoint()).x()
        bar.setValue(bar.maximum())
        self.app.processEvents()

        self.assertEqual(leading.mapTo(self.navigation, QPoint()).x(), leading_x)
        self.assertEqual(settings.mapTo(self.navigation, QPoint()).x(), settings_x)
        self.assertNotEqual(
            plugins[0].mapTo(self.navigation, QPoint()).x(), first_plugin_x
        )
        self.assertTrue(settings.isVisible())

    def test_viewport_wheel_prefers_pixel_then_maps_angle_deltas(self):
        self._add_scroll_items(12)
        settings = self.navigation.addItem(
            "settings",
            FluentIcon.SETTING,
            "Settings",
            position=NavigationItemPosition.BOTTOM,
        )
        self._show()

        bar = self.navigation.scrollArea.horizontalScrollBar()
        bar.setValue(40)

        pixel_x = _wheel_event(pixel=(-7, 30), angle=(120, 120))
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), pixel_x)
        self.assertEqual(bar.value(), 47)
        self.assertTrue(pixel_x.isAccepted())

        pixel_y = _wheel_event(pixel=(0, -9), angle=(120, 120))
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), pixel_y)
        self.assertEqual(bar.value(), 56)
        self.assertTrue(pixel_y.isAccepted())

        angle_x = _wheel_event(angle=(-120, 120))
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), angle_x)
        after_angle_x = bar.value()
        self.assertGreater(after_angle_x, 56)
        self.assertTrue(angle_x.isAccepted())

        angle_y = _wheel_event(angle=(0, -120))
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), angle_y)
        self.assertGreater(bar.value(), after_angle_x)
        self.assertTrue(angle_y.isAccepted())

        before_fixed_wheel = bar.value()
        fixed_wheel = _wheel_event(pixel=(0, -20))
        QApplication.sendEvent(settings, fixed_wheel)
        self.assertEqual(bar.value(), before_fixed_wheel)

    def test_wheel_stops_cleanly_at_scroll_boundaries(self):
        self._add_scroll_items(12)
        self._show()

        bar = self.navigation.scrollArea.horizontalScrollBar()
        bar.setValue(bar.maximum())
        at_end = _wheel_event(angle=(0, -120))
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), at_end)
        self.assertEqual(bar.value(), bar.maximum())
        self.assertFalse(at_end.isAccepted())

        bar.setValue(bar.minimum())
        at_start = _wheel_event(pixel=(25, 0))
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), at_start)
        self.assertEqual(bar.value(), bar.minimum())
        self.assertFalse(at_start.isAccepted())

        empty = _wheel_event()
        QApplication.sendEvent(self.navigation.scrollArea.viewport(), empty)
        self.assertFalse(empty.isAccepted())

    def test_selecting_scroll_item_reveals_it_without_moving_fixed_items(self):
        plugins = self._add_scroll_items(14)
        settings = self.navigation.addItem(
            "settings",
            FluentIcon.SETTING,
            "Settings",
            position=NavigationItemPosition.BOTTOM,
        )
        self._show()

        bar = self.navigation.scrollArea.horizontalScrollBar()
        settings_x = settings.mapTo(self.navigation, QPoint()).x()
        self.navigation.setCurrentItem("plugin-13")
        self.app.processEvents()

        item_position = plugins[-1].mapTo(
            self.navigation.scrollArea.viewport(), QPoint()
        )
        item_rect = QRect(item_position, plugins[-1].size())
        self.assertGreater(bar.value(), 0)
        viewport_rect = self.navigation.scrollArea.viewport().rect()
        self.assertTrue(viewport_rect.contains(item_rect))
        self.assertEqual(settings.mapTo(self.navigation, QPoint()).x(), settings_x)

        self.navigation.setCurrentItem("plugin-0")
        self.app.processEvents()
        self.assertEqual(bar.value(), bar.minimum())

        bar.setValue(bar.maximum() // 2)
        previous = bar.value()
        self.navigation.setCurrentItem("settings")
        self.assertEqual(bar.value(), previous)

    def test_dynamic_add_and_remove_updates_scroll_range(self):
        self._add_scroll_items(2)
        self._show()
        bar = self.navigation.scrollArea.horizontalScrollBar()
        self.assertEqual(bar.maximum(), 0)

        self._add_scroll_items(10)
        self.app.processEvents()
        self.assertGreater(bar.maximum(), 0)

        bar.setValue(bar.maximum())
        for index in range(2, 12):
            self.navigation.removeWidget(f"plugin-{index}")
        self.app.processEvents()

        self.assertEqual(bar.maximum(), 0)
        self.assertEqual(bar.value(), 0)
        self.assertEqual(set(self.navigation.scroll_items), {"plugin-0", "plugin-1"})


if __name__ == "__main__":
    unittest.main()
