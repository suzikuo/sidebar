import os
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from plugins.network_monitor.collector import NetworkSnapshot
from plugins.network_monitor.floating import FloatingNetworkWidget
from plugins.network_monitor.models import ApplicationTraffic
from plugins.network_monitor.monitor import TrafficRates
from plugins.network_monitor.plugin import NetworkMonitorPlugin
from plugins.network_monitor.views import NetworkMonitorWidget


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
        self.plugin_id = "network_monitor"
        self._temp_dir = tempfile.TemporaryDirectory()
        self._routes = {}

    def create_timer(self):
        return QTimer()

    def run_async(self, _callback, *_args):
        return None

    def get_data_dir(self):
        return self._temp_dir.name

    def register_api_route(
        self,
        action,
        handler,
        *,
        version="1.0",
        exported_capability=None,
    ):
        del exported_capability
        route = f"plugins/{self.plugin_id}/{action}"
        self._routes[route] = (handler, version)
        return route

    def call_api(self, route, payload=None, *, expected_version=None):
        handler, version = self._routes[route]
        if expected_version is not None:
            assert expected_version.split(".")[0] == version.split(".")[0]
        return handler(payload or {}, SimpleNamespace())

    def close(self):
        self._temp_dir.cleanup()

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
        self.assertEqual(widget.size().toTuple(), (300, 34))
        self.assertIn("1.5K", widget.proxy_upload_label.text())
        self.assertIn("2.0M", widget.proxy_download_label.text())
        self.assertIn("3.0K", widget.direct_upload_label.text())
        self.assertIn("4.0M", widget.direct_download_label.text())
        self.assertIn("#29A8FF", widget.proxy_upload_label.text())
        self.assertIn("#5CD46A", widget.proxy_download_label.text())
        self.assertIn("#5DB8FF", widget.proxy_title_label.styleSheet())
        self.assertIn("#FFB454", widget.direct_title_label.styleSheet())

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
        self.assertIn("#ABCDEF", widget.proxy_upload_label.text())
        self.assertIn("#ABCDEF", widget.direct_download_label.text())

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

    def test_layout_mode_scale_and_font_size_are_applied(self):
        widget = FloatingNetworkWidget()
        self.addCleanup(widget.close)

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_layout_mode": "double",
                "floating_scale": 120,
                "floating_font_size": 14,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()

        self.assertEqual(widget._layout_mode, "double")
        self.assertGreater(
            widget.proxy_download_label.geometry().top(),
            widget.proxy_upload_label.geometry().top(),
        )
        self.assertEqual(widget.size().toTuple(), (267, 66))
        self.assertIn("font-size: 14px", widget.proxy_upload_label.styleSheet())

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_layout_mode": "single",
                "floating_scale": 70,
                "floating_font_size": 8,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()
        self.assertEqual(
            widget.proxy_download_label.geometry().top(),
            widget.proxy_upload_label.geometry().top(),
        )
        self.assertEqual(widget.size().toTuple(), (218, 25))

        widget.apply_config(
            {
                "floating_enabled": True,
                "floating_layout_mode": "single",
                "floating_scale": 70,
                "floating_font_size": 18,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        self.app.processEvents()
        self.assertGreater(widget.width(), 300)
        self.assertGreater(widget.proxy_upload_label.width(), 50)

    def test_display_mode_can_show_system_and_v2ray_metadata(self):
        widget = FloatingNetworkWidget()
        self.addCleanup(widget.close)
        widget.apply_config(
            {
                "floating_display_mode": "system_proxy_direct",
                "floating_show_v2ray_metadata": True,
            }
        )
        widget.set_snapshot(
            NetworkSnapshot(
                system=TrafficRates(1, 2),
                proxy=TrafficRates(3, 4),
                direct=TrafficRates(5, 6),
                v2rayn_enabled=True,
                v2rayn_connected=True,
                v2ray_node="node-a",
                v2ray_latency_ms=36,
                v2ray_route="proxy",
            )
        )
        widget.show()
        self.app.processEvents()

        self.assertTrue(widget.system_title_label.isVisible())
        self.assertTrue(widget.proxy_title_label.isVisible())
        self.assertTrue(widget.direct_title_label.isVisible())
        self.assertIn("node-a", widget.v2ray_metadata_label.text())
        self.assertIn("36 ms", widget.v2ray_metadata_label.text())
        self.assertGreaterEqual(widget.width(), 300)
        self.assertEqual(
            widget.v2ray_metadata_label.toolTip(),
            widget.v2ray_metadata_label.text(),
        )

    def test_detail_panel_fits_narrow_width_without_horizontal_scrolling(self):
        widget = NetworkMonitorWidget()
        self.addCleanup(widget.close)
        widget.resize(360, 720)
        widget.show()
        self.app.processEvents()

        self.assertEqual(widget.scroll.horizontalScrollBar().maximum(), 0)
        self.assertEqual(widget.app_table.horizontalScrollBar().maximum(), 0)
        self.assertTrue(widget.app_table.isColumnHidden(1))
        self.assertTrue(widget.app_table.isColumnHidden(2))

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
        widget.layout_mode_combo.setCurrentText("双行")
        widget.layout_scale_slider.setValue(120)
        widget.font_size_input.setValue(14)

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
        self.assertEqual(changes[-1]["floating_layout_mode"], "double")
        self.assertEqual(changes[-1]["floating_scale"], 120)
        self.assertEqual(changes[-1]["floating_font_size"], 14)

    def test_history_refreshes_while_visible_and_name_sort_is_stable(self):
        widget = NetworkMonitorWidget()
        self.addCleanup(widget.close)
        requests = []
        widget.history_requested.connect(lambda range_key, source: requests.append((range_key, source)))
        widget._switch_page("history")
        widget._last_history_request = 0
        widget.app_sort_combo.setCurrentIndex(widget.app_sort_combo.findData("name"))
        snapshot = NetworkSnapshot(
            system=TrafficRates(10, 20),
            proxy=TrafficRates(1, 2),
            direct=TrafficRates(9, 18),
            v2rayn_enabled=True,
            v2rayn_connected=True,
            applications=(
                ApplicationTraffic(2, "zeta.exe", "", "zeta", 10, 10, 10, 10),
                ApplicationTraffic(1, "alpha.exe", "", "alpha", 1, 1, 1, 1),
            ),
            app_monitor_available=True,
        )

        widget.set_snapshot(snapshot)

        self.assertGreaterEqual(len(requests), 2)
        self.assertEqual(widget.app_table.item(0, 0).text(), "alpha.exe")

    def test_application_rows_survive_short_idle_period_then_expire(self):
        widget = NetworkMonitorWidget()
        self.addCleanup(widget.close)
        traffic = ApplicationTraffic(
            7,
            "chrome.exe",
            "C:/chrome.exe",
            "chrome",
            10,
            20,
            10,
            20,
        )

        with patch("plugins.network_monitor.views.time.monotonic", return_value=10):
            widget._set_applications((traffic,))
        with patch("plugins.network_monitor.views.time.monotonic", return_value=12):
            widget._set_applications(())

        self.assertEqual(widget.app_table.rowCount(), 1)
        self.assertEqual(widget.app_table.item(0, 3).text(), "0 B/s")
        self.assertEqual(widget.app_table.item(0, 4).text(), "0 B/s")

        with patch("plugins.network_monitor.views.time.monotonic", return_value=16):
            widget._set_applications(())

        self.assertEqual(widget.app_table.rowCount(), 0)

    def test_plugin_load_restores_visible_floating_widget(self):
        context = _Context(
            {
                "floating_enabled": True,
                "floating_x": 40,
                "floating_y": 50,
            }
        )
        plugin = NetworkMonitorPlugin(context)
        self.addCleanup(context.close)
        self.addCleanup(plugin.on_unload)

        plugin.on_load()
        self.app.processEvents()

        self.assertTrue(plugin._floating_widget.isVisible())
        self.assertIsNone(plugin.get_sidebar_widget())


if __name__ == "__main__":
    unittest.main()
