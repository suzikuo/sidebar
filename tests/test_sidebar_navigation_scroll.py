import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel
from qfluentwidgets import FluentIcon, NavigationItemPosition

from core.state_store import StateStore
from core.window_system.sidebar import SidebarWindow


class SidebarNavigationScrollTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _sidebar(self, root: str, edge: str) -> SidebarWindow:
        store = StateStore(str(Path(root) / f"{edge}.json"))
        store.set("settings", {"appearance": {"sidebar_position": edge}})
        sidebar = SidebarWindow(store)
        sidebar.resize(80, 300)
        sidebar.show()
        sidebar.navigationInterface.show()
        return sidebar

    def test_vertical_plugins_scroll_while_settings_remains_fixed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for edge in ("left", "right"):
                with self.subTest(edge=edge):
                    sidebar = self._sidebar(temp_dir, edge)
                    for index in range(12):
                        sidebar.add_item(
                            f"plugin-{index}",
                            FluentIcon.APPLICATION,
                            f"Plugin {index}",
                            NavigationItemPosition.SCROLL,
                        )
                    sidebar.add_item(
                        "settings",
                        FluentIcon.SETTING,
                        "Settings",
                        NavigationItemPosition.BOTTOM,
                    )
                    self.app.processEvents()

                    panel = sidebar.navigationInterface.panel
                    scroll_bar = panel.scrollArea.verticalScrollBar()
                    settings_y = sidebar.items["settings"].geometry().y()

                    self.assertIs(sidebar.items["plugin-0"].parent(), panel.scrollWidget)
                    self.assertIsNot(sidebar.items["settings"].parent(), panel.scrollWidget)
                    self.assertGreater(scroll_bar.maximum(), 0)

                    sidebar.set_current_item("plugin-11")
                    self.app.processEvents()

                    self.assertGreater(scroll_bar.value(), 0)
                    self.assertEqual(sidebar.items["settings"].geometry().y(), settings_y)

                    order = [f"plugin-{index}" for index in reversed(range(12))]
                    sidebar.update_plugin_order(order)
                    self.app.processEvents()
                    actual_order = [
                        panel.scrollLayout.itemAt(index).widget().property("routeKey")
                        for index in range(panel.scrollLayout.count())
                    ]
                    self.assertEqual(actual_order, order)

                    sidebar.close()
                    self.app.processEvents()

    def test_plugin_sidebar_content_stays_before_fixed_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for edge in ("left", "right", "top"):
                with self.subTest(edge=edge):
                    sidebar = self._sidebar(temp_dir, edge)
                    sidebar.add_item(
                        "plugin",
                        FluentIcon.APPLICATION,
                        "Plugin",
                        NavigationItemPosition.SCROLL,
                    )
                    sidebar.add_item(
                        "settings",
                        FluentIcon.SETTING,
                        "Settings",
                        NavigationItemPosition.BOTTOM,
                    )
                    extra = QLabel("Plugin information")
                    sidebar.add_sidebar_widget(extra, stretch=True)
                    self.app.processEvents()

                    navigation = sidebar.navigationInterface
                    scroll_widget = (
                        navigation.scrollWidget
                        if edge == "top"
                        else navigation.panel.scrollWidget
                    )
                    settings = sidebar.items["settings"]

                    self.assertIs(extra.parent(), scroll_widget)
                    self.assertIsNot(settings.parent(), scroll_widget)
                    if edge == "top":
                        self.assertGreaterEqual(
                            settings.mapTo(navigation, QPoint()).x(),
                            extra.mapTo(navigation, QPoint()).x(),
                        )
                    else:
                        self.assertGreaterEqual(
                            settings.mapTo(navigation, QPoint()).y(),
                            extra.mapTo(navigation, QPoint()).y(),
                        )

                    sidebar.close()
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
