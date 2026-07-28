import unittest

from builtin_plugins.network_monitor.records import MinuteHistoryBuffer


def _record(timestamp, upload, download, upload_rate, download_rate):
    return {
        "timestamp": timestamp,
        "source": "system",
        "appKey": "__system__",
        "appName": "系统",
        "appPath": "",
        "pid": 0,
        "uploadBytes": upload,
        "downloadBytes": download,
        "peakUploadBps": upload_rate,
        "peakDownloadBps": download_rate,
        "sampleCount": 1,
    }


class MinuteHistoryBufferTest(unittest.TestCase):
    def test_records_are_merged_until_the_next_minute(self):
        buffer = MinuteHistoryBuffer()

        self.assertEqual(buffer.add((_record(120, 10, 20, 10, 20),)), ())
        self.assertEqual(buffer.add((_record(121, 30, 40, 30, 40),)), ())
        flushed = buffer.add((_record(180, 50, 60, 50, 60),))

        self.assertEqual(len(flushed), 1)
        record = flushed[0]
        self.assertEqual(record["timestamp"], 120)
        self.assertEqual(record["uploadBytes"], 40)
        self.assertEqual(record["downloadBytes"], 60)
        self.assertEqual(record["peakUploadBps"], 30)
        self.assertEqual(record["peakDownloadBps"], 40)
        self.assertEqual(record["sampleCount"], 2)

    def test_flush_persists_a_partial_minute_on_shutdown(self):
        buffer = MinuteHistoryBuffer()
        buffer.add((_record(120, 10, 20, 10, 20),))

        flushed = buffer.flush()

        self.assertEqual(len(flushed), 1)
        self.assertEqual(flushed[0]["timestamp"], 120)
        self.assertEqual(flushed[0]["uploadBytes"], 10)


if __name__ == "__main__":
    unittest.main()
