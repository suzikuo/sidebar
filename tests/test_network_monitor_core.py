import json
import unittest
from types import SimpleNamespace

from plugins.network_monitor.monitor import (
    TrafficCounters,
    TrafficRateSampler,
    WindowsNetworkMonitor,
)
from plugins.network_monitor.v2ray import (
    V2RayNMetricsClient,
    V2RayNMetricsConfig,
    V2RayNMetricsError,
    parse_proxy_counters,
)
from plugins.network_monitor.v2ray_source import V2RayCollector


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return self._payload


class NetworkMonitorCoreTest(unittest.TestCase):
    def test_default_route_scope_uses_only_the_selected_interface(self):
        rows = (
            SimpleNamespace(
                InterfaceIndex=5,
                OperStatus=1,
                Type=6,
                OutOctets=100,
                InOctets=200,
            ),
            SimpleNamespace(
                InterfaceIndex=7,
                OperStatus=1,
                Type=6,
                OutOctets=300,
                InOctets=400,
            ),
            SimpleNamespace(
                InterfaceIndex=9,
                OperStatus=1,
                Type=24,
                OutOctets=500,
                InOctets=600,
            ),
        )

        selected, matched = WindowsNetworkMonitor._aggregate_counters(rows, 7)
        aggregate, _ = WindowsNetworkMonitor._aggregate_counters(rows)

        self.assertTrue(matched)
        self.assertEqual(selected, TrafficCounters(300, 400))
        self.assertEqual(aggregate, TrafficCounters(400, 600))

    def test_rate_sampler_uses_elapsed_time_and_resets_on_counter_regression(self):
        sampler = TrafficRateSampler()

        first = sampler.sample(TrafficCounters(100, 200), now=10)
        second = sampler.sample(TrafficCounters(400, 800), now=12)
        reset = sampler.sample(TrafficCounters(50, 60), now=13)

        self.assertEqual(first.upload_bytes_per_second, 0)
        self.assertEqual(first.download_bytes_per_second, 0)
        self.assertEqual(second.upload_bytes_per_second, 150)
        self.assertEqual(second.download_bytes_per_second, 300)
        self.assertEqual(reset.upload_bytes_per_second, 0)
        self.assertEqual(reset.download_bytes_per_second, 0)

    def test_metrics_parser_sums_proxy_tags_and_ignores_direct(self):
        counters = parse_proxy_counters(
            {
                "stats": {
                    "outbound": {
                        "proxy": {"uplink": 100, "downlink": 200},
                        "proxy-2": {"uplink": 30, "downlink": 40},
                        "direct": {"uplink": 999, "downlink": 999},
                    }
                }
            }
        )

        self.assertEqual(counters, TrafficCounters(130, 240))

    def test_metrics_client_reads_debug_vars(self):
        payload = json.dumps(
            {"stats": {"outbound": {"proxy": {"uplink": 11, "downlink": 22}}}}
        ).encode("utf-8")
        captured = {}

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return _Response(payload)

        client = V2RayNMetricsClient(
            V2RayNMetricsConfig("127.0.0.1", 21193, 1.5),
            opener=opener,
        )

        self.assertEqual(client.read_counters(), TrafficCounters(11, 22))
        self.assertEqual(captured["url"], "http://127.0.0.1:21193/debug/vars")
        self.assertEqual(captured["timeout"], 1.5)

    def test_metrics_rejects_non_loopback_and_missing_proxy(self):
        with self.assertRaises(ValueError):
            V2RayNMetricsConfig("192.168.1.5", 21193)
        with self.assertRaises(V2RayNMetricsError):
            parse_proxy_counters({"stats": {"outbound": {"direct": {}}}})

    def test_failed_metrics_collection_uses_exponential_backoff(self):
        attempts = []
        clock_values = iter((0.0, 0.5, 1.0, 2.0))

        class FailingClient:
            def read_counters(self):
                attempts.append(True)
                raise OSError("offline")

        collector = V2RayCollector(
            client_factory=lambda _config: FailingClient(),
            clock=lambda: next(clock_values),
            wall_clock=lambda: 100,
        )
        config = {"enabled": True, "refresh_interval_ms": 1000}

        snapshots = [collector.collect(config) for _ in range(4)]

        self.assertEqual(len(attempts), 2)
        self.assertTrue(all(not snapshot.connected for snapshot in snapshots))
        self.assertTrue(all(snapshot.error == "offline" for snapshot in snapshots))


if __name__ == "__main__":
    unittest.main()
