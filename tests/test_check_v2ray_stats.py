import io
import unittest

from builtin_plugins.network_monitor.monitor import TrafficCounters
from check_v2ray_stats import build_parser, run_monitor


class _Client:
    def __init__(self, counters):
        self._counters = iter(counters)

    def read_counters(self):
        return next(self._counters)


class V2RayStatsCheckScriptTest(unittest.TestCase):
    def test_monitor_prints_raw_counters_and_detects_rate_change(self):
        output = io.StringIO()
        clocks = iter((10.0, 11.0))
        client = _Client(
            (
                TrafficCounters(1000, 2000),
                TrafficCounters(1400, 3000),
            )
        )

        changed = run_monitor(
            client,
            interval=1.0,
            count=2,
            stream=output,
            clock=lambda: next(clocks),
            sleep=lambda _seconds: None,
        )

        self.assertTrue(changed)
        rendered = output.getvalue()
        self.assertIn("累计 ↑ 1,000 B", rendered)
        self.assertIn("实时 ↑ 400 B/s", rendered)
        self.assertIn("↓ 1000 B/s", rendered)

    def test_monitor_reports_no_change_for_stable_counters(self):
        output = io.StringIO()
        clocks = iter((1.0, 2.0))
        counters = TrafficCounters(100, 200)

        changed = run_monitor(
            _Client((counters, counters)),
            interval=1.0,
            count=2,
            stream=output,
            clock=lambda: next(clocks),
            sleep=lambda _seconds: None,
        )

        self.assertFalse(changed)
        self.assertIn("实时 ↑ 0 B/s  ↓ 0 B/s", output.getvalue())

    def test_default_port_matches_current_v2rayn_metrics(self):
        args = build_parser().parse_args([])

        self.assertEqual(args.port, 21193)
        self.assertEqual(args.count, 10)


if __name__ == "__main__":
    unittest.main()
