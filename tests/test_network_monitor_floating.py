import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from builtin_plugins.network_monitor.collector import NetworkSnapshot
from builtin_plugins.network_monitor.floating import FloatingNetworkWidget
from builtin_plugins.network_monitor.monitor import TrafficRates
from builtin_plugins.network_monitor.plugin import NetworkMonitorPlugin
from builtin_plugins.network_monitor.views import NetworkMonitorWidget


class _State:
    def __init__(self, config):
        self.values = {"config": config}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _Context:
    def __init__(self, config):
        self.state = _State(config)
        self.detail_opened = False

    def create_timer(self):
        return QTimer()

    def run_async(self, _callback, *_args):
        return None

    def open_detail_view(self):
        self.detail_opened = True


class FloatingNetworkWidgetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_widget_is_transparent_topmost_and_shows_proxy_and_direct_only(self):
        widget = FloatingNetworkWidget()
        self.addCleanup(widget.close)
        snapshot = NetworkSnapshot(
            system=TrafficRates(99 * 1024 * 1024, 88 * 1024 * 1024),
            proxy=TrafficRates(1536.0, 2 * 1024 * 1024),
            direct=TrafficRates(3 * 1024.0, 4 * 1024 * 1024),
            v2rayn_enabled=True,
            v2rayn_connected=True,
        )

        widget.set_snapshot(snapshot)

        self.assertTrue(widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(
            widget.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        )
        self.assertEqual(widget.size().toTuple(), (246, 54))
        self.assertEqual(widget.proxy_upload_label.text(), "1.5KB/s")
        self.assertEqual(widget.proxy_download_label.text(), "2.0MB/s")
        self.assertEqual(widget.direct_upload_label.text(), "3.0KB/s")
        self.assertEqual(widget.direct_download_label.text(), "4.0MB/s")

    def test_config_controls_visibility_and_position(self):
        widget = FloatingNetworkWidget()
        self.addCleanup(widget.close)

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()
        self.assertTrue(widget.isVisible())

        widget.apply_config(
            {
                "floating_enabled": False,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()
        self.assertFalse(widget.isVisible())

    def test_config_applies_background_opacity_and_font_color(self):
        widget = FloatingNetworkWidget()
        self.addCleanup(widget.close)

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_background_color": "#123456",
                "floating_background_opacity": 50,
                "floating_font_color": "#ABCDEF",
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()

        self.assertEqual(widget._background_color.name().upper(), "#123456")
        self.assertIn(widget._background_color.alpha(), (127, 128))
        self.assertEqual(widget._font_color, "#ABCDEF")
        self.assertTrue(
            all("#ABCDEF" in label.styleSheet() for label in widget._text_labels)
        )

    def test_lock_enables_input_transparency_and_disables_dragging(self):
        widget = FloatingNetworkWidget()
        self.addCleanup(widget.close)

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_locked": True,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()

        self.assertTrue(widget._is_locked)
        self.assertTrue(
            widget.windowFlags() & Qt.WindowType.WindowTransparentForInput
        )

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_locked": False,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()
        self.assertFalse(widget._is_locked)
        self.assertFalse(
            widget.windowFlags() & Qt.WindowType.WindowTransparentForInput
        )

    def test_detail_panel_fits_narrow_width_without_horizontal_scrolling(self):
        widget = NetworkMonitorWidget()
        self.addCleanup(widget.close)
        widget.resize(360, 720)
        widget.show()
        self.app.processEvents()

        self.assertEqual(widget.scroll.horizontalScrollBar().maximum(), 0)

    def test_floating_switch_applies_without_save_button_click(self):
        widget = NetworkMonitorWidget()
        self.addCleanup(widget.close)
        changes = []
        widget.config_changed.connect(changes.append)

        widget.floating_switch.setChecked(True)

        self.assertTrue(changes)
        self.assertTrue(changes[-1]["floating_enabled"])

    def test_floating_appearance_is_included_in_saved_config(self):
        widget = NetworkMonitorWidget()
        self.addCleanup(widget.close)
        changes = []
        widget.config_changed.connect(changes.append)
        widget.background_color_picker.setColor(QColor("#123456"))
        widget.background_opacity_slider.setValue(35)
        widget.font_color_picker.setColor(QColor("#ABCDEF"))

        widget._save()

        self.assertEqual(
            changes[-1]["floating_background_color"].upper(),
            "#123456",
        )
        self.assertEqual(changes[-1]["floating_background_opacity"], 35)
        self.assertEqual(
            changes[-1]["floating_font_color"].upper(),
            "#ABCDEF",
        )

    def test_plugin_load_restores_visible_floating_widget(self):
        context = _Context(
            {
                "floating_enabled": True,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        plugin = NetworkMonitorPlugin(context)
        self.addCleanup(plugin.on_unload)

        plugin.on_load()
        self.app.processEvents()

        self.assertTrue(plugin._floating_widget.isVisible())
        self.assertIsNone(plugin.get_sidebar_widget())


if __name__ == "__main__":
    unittest.main()
