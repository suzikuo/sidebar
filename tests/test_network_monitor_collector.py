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

    def read_counters(self):
        value = next(self._values)
        if isinstance(value, Exception):
            raise value
        return value


class _Clock:
    def __init__(self, *values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


class NetworkMonitorCollectorTest(unittest.TestCase):
    def test_proxy_rates_are_subtracted_from_system_rates(self):
        system = _CounterSource(
            [TrafficCounters(1000, 2000), TrafficCounters(1600, 3200)]
        )
        proxy = _CounterSource(
            [TrafficCounters(100, 200), TrafficCounters(300, 500)]
        )
        collector = NetworkMonitorCollector(
            system_monitor=system,
            v2rayn_client_factory=lambda _config: proxy,
            clock=_Clock(10.0, 11.0),
        )
        config = {**DEFAULT_CONFIG, "v2rayn_enabled": True}

        collector.collect(config)
        snapshot = collector.collect(config)

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
        proxy = _CounterSource(
            [TrafficCounters(100, 100), TrafficCounters(400, 500)]
        )
        collector = NetworkMonitorCollector(
            system_monitor=system,
            v2rayn_client_factory=lambda _config: proxy,
            clock=_Clock(1.0, 2.0),
        )
        config = {**DEFAULT_CONFIG, "v2rayn_enabled": True}

        collector.collect(config)
        snapshot = collector.collect(config)

        self.assertEqual(snapshot.direct.upload_bytes_per_second, 0.0)
        self.assertEqual(snapshot.direct.download_bytes_per_second, 0.0)

    def test_proxy_failure_does_not_report_system_rate_as_direct(self):
        system = _CounterSource([TrafficCounters(100, 200)])
        proxy = _CounterSource([RuntimeError("API unavailable")])
        collector = NetworkMonitorCollector(
            system_monitor=system,
            v2rayn_client_factory=lambda _config: proxy,
            clock=_Clock(1.0),
        )

        snapshot = collector.collect(
            {**DEFAULT_CONFIG, "v2rayn_enabled": True}
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
        )

        config = {**DEFAULT_CONFIG, "v2rayn_enabled": False}
        collector.collect(config)
        snapshot = collector.collect(config)

        self.assertEqual(snapshot.proxy.upload_bytes_per_second, 0.0)
        self.assertEqual(snapshot.proxy.download_bytes_per_second, 0.0)
        self.assertEqual(snapshot.direct, snapshot.system)

    def test_config_is_bounded_and_rejects_non_loopback_api(self):
        normalized = normalize_config(
            {
                "refresh_interval_ms": 1,
                "timeout_ms": 99999,
                "floating_background_opacity": 999,
                "floating_background_color": "invalid",
                "floating_font_color": "#abcdef",
                "floating_locked": True,
            }
        )
        self.assertEqual(normalized["refresh_interval_ms"], 500)
        self.assertEqual(normalized["timeout_ms"], 10000)
        self.assertEqual(normalized["floating_background_opacity"], 100)
        self.assertEqual(normalized["floating_background_color"], "#202327")
        self.assertEqual(normalized["floating_font_color"], "#ABCDEF")
        self.assertTrue(normalized["floating_locked"])

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
