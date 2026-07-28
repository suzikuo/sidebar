import unittest

from builtin_plugins.network_monitor.collector import (
    DEFAULT_CONFIG,
    NetworkMonitorCollector,
    normalize_config,
    validate_config,
)
from builtin_plugins.network_monitor.monitor import TrafficCounters


class _CounterSource:
    def __init__(self, values):
        self._values = iter(values)

    def read_counters(self, _scope):
        value = next(self._values)
        if isinstance(value, Exception):
            raise value
        return value


class _Clock:
    def __init__(self, *values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


class _ApplicationSource:
    def drain(self, interval_seconds):
        raise AssertionError(f"unexpected application drain: {interval_seconds}")


def _proxy_snapshot(upload, download, timestamp):
    return {
        "enabled": True,
        "connected": True,
        "uploadSpeed": upload,
        "downloadSpeed": download,
        "timestamp": timestamp,
    }


class NetworkMonitorCollectorTest(unittest.TestCase):
    def test_proxy_rates_are_subtracted_from_system_rates(self):
        system = _CounterSource(
            [TrafficCounters(1000, 2000), TrafficCounters(1600, 3200)]
        )
        collector = NetworkMonitorCollector(
            system_monitor=system,
            clock=_Clock(10.0, 11.0),
            wall_clock=_Clock(100.0, 101.0),
        )
        config = {**DEFAULT_CONFIG, "v2rayn_enabled": True}

        collector.collect(config, proxy_snapshot=_proxy_snapshot(0, 0, 100))
        snapshot = collector.collect(
            config,
            proxy_snapshot=_proxy_snapshot(200, 300, 101),
        )

        self.assertEqual(snapshot.system.upload_bytes_per_second, 600.0)
        self.assertEqual(snapshot.system.download_bytes_per_second, 1200.0)
        self.assertEqual(snapshot.proxy.upload_bytes_per_second, 200.0)
        self.assertEqual(snapshot.proxy.download_bytes_per_second, 300.0)
        self.assertEqual(snapshot.direct.upload_bytes_per_second, 400.0)
        self.assertEqual(snapshot.direct.download_bytes_per_second, 900.0)

    def test_direct_rates_are_clamped_to_zero(self):
        system = _CounterSource(
            [TrafficCounters(100, 100), TrafficCounters(200, 200)]
        )
        collector = NetworkMonitorCollector(
            system_monitor=system,
            clock=_Clock(1.0, 2.0),
            wall_clock=_Clock(10.0, 11.0),
        )
        config = {**DEFAULT_CONFIG, "v2rayn_enabled": True}

        collector.collect(config, proxy_snapshot=_proxy_snapshot(0, 0, 10))
        snapshot = collector.collect(
            config,
            proxy_snapshot=_proxy_snapshot(300, 400, 11),
        )

        self.assertEqual(snapshot.direct.upload_bytes_per_second, 0.0)
        self.assertEqual(snapshot.direct.download_bytes_per_second, 0.0)

    def test_proxy_failure_does_not_report_system_rate_as_direct(self):
        system = _CounterSource([TrafficCounters(100, 200)])
        collector = NetworkMonitorCollector(
            system_monitor=system,
            clock=_Clock(1.0),
            wall_clock=_Clock(10.0),
        )

        snapshot = collector.collect(
            {**DEFAULT_CONFIG, "v2rayn_enabled": True},
            proxy_snapshot={
                "enabled": True,
                "connected": False,
                "error": "API unavailable",
                "timestamp": 10,
            },
        )

        self.assertIsNotNone(snapshot.system)
        self.assertIsNone(snapshot.proxy)
        self.assertIsNone(snapshot.direct)
        self.assertFalse(snapshot.v2rayn_connected)
        self.assertIn("API unavailable", snapshot.proxy_error)

    def test_disabled_proxy_is_zero_and_direct_matches_system(self):
        system = _CounterSource(
            [TrafficCounters(100, 200), TrafficCounters(300, 600)]
        )
        collector = NetworkMonitorCollector(
            system_monitor=system,
            clock=_Clock(4.0, 5.0),
            wall_clock=_Clock(20.0, 21.0),
        )

        config = {**DEFAULT_CONFIG, "v2rayn_enabled": False}
        disabled = {"enabled": False, "connected": False, "timestamp": 20}
        collector.collect(config, proxy_snapshot=disabled)
        disabled["timestamp"] = 21
        snapshot = collector.collect(config, proxy_snapshot=disabled)

        self.assertEqual(snapshot.proxy.upload_bytes_per_second, 0.0)
        self.assertEqual(snapshot.proxy.download_bytes_per_second, 0.0)
        self.assertEqual(snapshot.direct, snapshot.system)

    def test_disabled_application_monitor_does_not_drain_etw_source(self):
        collector = NetworkMonitorCollector(
            system_monitor=_CounterSource([TrafficCounters(100, 200)]),
            application_source=_ApplicationSource(),
            clock=_Clock(1.0),
            wall_clock=_Clock(10.0),
        )

        snapshot = collector.collect(
            {**DEFAULT_CONFIG, "application_monitor_enabled": False},
            proxy_snapshot={"enabled": False, "connected": False, "timestamp": 10},
        )

        self.assertFalse(snapshot.app_monitor_available)
        self.assertEqual(snapshot.app_monitor_error, "应用流量监控已关闭。")

    def test_config_is_bounded_and_rejects_non_loopback_api(self):
        normalized = normalize_config(
            {
                "refresh_interval_ms": 1,
                "timeout_ms": 99999,
                "floating_background_opacity": 999,
                "floating_background_color": "invalid",
                "floating_font_color": "#abcdef",
                "floating_locked": True,
                "floating_layout_mode": "invalid",
                "floating_scale": 999,
                "floating_font_size": 1,
            }
        )
        self.assertEqual(normalized["refresh_interval_ms"], 500)
        self.assertEqual(normalized["timeout_ms"], 10000)
        self.assertEqual(normalized["floating_background_opacity"], 100)
        self.assertEqual(normalized["floating_background_color"], "#202327")
        self.assertEqual(normalized["floating_font_color"], "#ABCDEF")
        self.assertTrue(normalized["floating_locked"])
        self.assertEqual(normalized["floating_layout_mode"], "single")
        self.assertEqual(normalized["floating_scale"], 140)
        self.assertEqual(normalized["floating_font_size"], 8)
        self.assertFalse(normalized["application_monitor_enabled"])
        self.assertEqual(normalized["network_scope"], "default_route")
        self.assertEqual(
            normalize_config({"network_scope": "all_active"})["network_scope"],
            "all_active",
        )

        with self.assertRaises(ValueError):
            validate_config(
                {
                    **DEFAULT_CONFIG,
                    "v2rayn_enabled": True,
                    "v2rayn_host": "192.168.1.1",
                }
            )


if __name__ == "__main__":
    unittest.main()
