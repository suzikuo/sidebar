import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtWidgets import QApplication

from plugins.time.desktop_clock import DesktopClockWidget
from plugins.time.plugin import TimePlugin
from plugins.time.tick_scheduler import next_tick_delay_ms


class TimePerformanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_minute_display_aligns_to_minute_boundary(self):
        self.assertEqual(
            next_tick_delay_ms(
                "HH:mm",
                current_second=15,
                current_millisecond=250,
            ),
            44750,
        )

    def test_seconds_and_near_alarm_use_second_boundary(self):
        self.assertEqual(
            next_tick_delay_ms(
                "HH:mm:ss",
                current_second=15,
                current_millisecond=250,
            ),
            750,
        )
        self.assertEqual(
            next_tick_delay_ms(
                "HH:mm",
                current_second=15,
                current_millisecond=250,
                alarm_remaining_seconds=299,
            ),
            750,
        )

    def test_timer_wakes_when_alarm_enters_countdown_window(self):
        self.assertEqual(
            next_tick_delay_ms(
                "HH:mm",
                current_second=15,
                current_millisecond=0,
                alarm_remaining_seconds=301.2,
            ),
            1200,
        )

    def test_desktop_clock_stops_timer_while_hidden(self):
        widget = DesktopClockWidget()
        self.addCleanup(widget.close)
        self.assertFalse(widget.timer.isActive())

        widget.show()
        self.app.processEvents()
        self.assertTrue(widget.timer.isActive())

        widget.hide()
        self.app.processEvents()
        self.assertFalse(widget.timer.isActive())

    @patch("plugins.time.plugin.DesktopClockWidget")
    @patch("plugins.time.plugin.AlarmManager")
    def test_time_plugin_creates_desktop_window_only_when_enabled(
        self,
        alarm_manager_class,
        desktop_clock_class,
    ):
        state = MagicMock()
        state.get.return_value = {
            "enabled": True,
            "format": "HH:mm",
            "color": "white",
            "show_desktop": False,
        }
        context = MagicMock()
        context.state = state
        plugin = TimePlugin(context)

        plugin.on_load()
        desktop_clock_class.assert_not_called()

        enabled = {
            "enabled": True,
            "format": "HH:mm",
            "color": "white",
            "show_desktop": True,
        }
        plugin._on_config_changed(enabled)
        desktop_clock_class.assert_called_once()
        desktop_clock = desktop_clock_class.return_value
        desktop_clock.show.assert_called_once()

        plugin._on_config_changed({**enabled, "show_desktop": False})
        desktop_clock.close.assert_called_once()
        desktop_clock.deleteLater.assert_called_once()
        self.assertIsNone(plugin._desktop_clock)
        alarm_manager_class.assert_called_once_with(context)


if __name__ == "__main__":
    unittest.main()
