import tempfile
import unittest
from pathlib import Path

from plugins.network_monitor.history_models import TrafficRecord
from plugins.network_monitor.history_repository import TrafficHistoryRepository


class TrafficHistoryRepositoryTest(unittest.TestCase):
    def test_sources_are_separate_and_rollups_are_idempotent(self):
        base = 1_700_000_000
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TrafficHistoryRepository(
                Path(temp_dir) / "traffic.db", clock=lambda: base + 60
            )
            try:
                service.submit(
                    (
                        TrafficRecord(base + 1, "system", "__system__", "系统", "", 0, 100, 200, 100, 200),
                        TrafficRecord(base + 1, "v2ray", "__v2ray__", "V2Ray", "", 0, 30, 40, 30, 40),
                        TrafficRecord(base + 2, "application", "chrome", "chrome.exe", "C:/chrome.exe", 7, 50, 80, 50, 80),
                    ),
                    now=base + 2,
                )
                service.maintain(base + 60)

                system = service.query("hour", source="system", now=base + 60)
                v2ray = service.query("hour", source="v2ray", now=base + 60)
                self.assertEqual(system.total_upload_bytes, 100)
                self.assertEqual(system.total_download_bytes, 200)
                self.assertEqual(v2ray.total_upload_bytes, 30)
                self.assertEqual(v2ray.total_download_bytes, 40)
                self.assertEqual(system.ranking[0].app_name, "chrome.exe")
                counts_before = service.row_counts()
                service.maintain(base + 60)
                self.assertEqual(service.row_counts(), counts_before)
            finally:
                service.close()

    def test_second_rows_expire_after_one_hour_but_minute_rollup_remains(self):
        base = 1_700_000_000
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TrafficHistoryRepository(
                Path(temp_dir) / "traffic.db", clock=lambda: base + 3700
            )
            try:
                service.submit(
                    (
                        TrafficRecord(base + 1, "system", "__system__", "系统", "", 0, 5, 6, 5, 6),
                    ),
                    now=base + 1,
                )
                service.maintain(base + 3700)
                counts = service.row_counts()
                self.assertEqual(counts["traffic_second"], 0)
                self.assertGreaterEqual(counts["traffic_minute"], 1)
            finally:
                service.close()

    def test_year_query_uses_retained_day_rollup(self):
        now = 1_750_000_000
        sample_time = now - 40 * 24 * 60 * 60
        with tempfile.TemporaryDirectory() as temp_dir:
            service = TrafficHistoryRepository(
                Path(temp_dir) / "traffic.db",
                clock=lambda: now,
            )
            try:
                service.submit(
                    (
                        TrafficRecord(
                            sample_time,
                            "system",
                            "__system__",
                            "系统",
                            "",
                            0,
                            700,
                            900,
                            700,
                            900,
                        ),
                    ),
                    now=sample_time,
                )
                service.maintain(now)

                result = service.query("365days", source="system", now=now)

                self.assertEqual(result.resolution, "day")
                self.assertEqual(result.total_upload_bytes, 700)
                self.assertEqual(result.total_download_bytes, 900)
                counts = service.row_counts()
                self.assertEqual(counts["traffic_second"], 0)
                self.assertEqual(counts["traffic_minute"], 0)
                self.assertEqual(counts["traffic_hour"], 0)
                self.assertGreaterEqual(counts["traffic_day"], 1)
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
