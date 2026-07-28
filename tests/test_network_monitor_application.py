import unittest

from builtin_plugins.network_monitor.application import parse_etw_traffic_event


class EtwApplicationTrafficTest(unittest.TestCase):
    def test_tcp_and_udp_events_are_classified_by_opcode(self):
        header = {"ProcessId": 1234}
        self.assertEqual(
            parse_etw_traffic_event(
                (10, {"PID": 1234, "size": 4096, "EventHeader": header})
            ),
            (1234, 4096, 0),
        )
        self.assertEqual(
            parse_etw_traffic_event(
                (43, {"size": 512, "EventHeader": header})
            ),
            (1234, 0, 512),
        )

    def test_non_traffic_or_invalid_events_are_ignored(self):
        self.assertIsNone(parse_etw_traffic_event((12, {"PID": 1, "size": 4})))
        self.assertIsNone(parse_etw_traffic_event((10, {"PID": 1, "size": 0})))
        self.assertEqual(
            parse_etw_traffic_event((10, {"PID": 0, "size": 4})),
            (0, 4, 0),
        )


if __name__ == "__main__":
    unittest.main()
