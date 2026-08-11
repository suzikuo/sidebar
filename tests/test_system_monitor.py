import os
import unittest

from plugins.system_monitor.collector import SystemCollector


class FakeBackend:
    def __init__(self):
        self.index = 0
        self.terminated = []

    def system_times(self):
        values = ((100, 500, 500), (120, 600, 600))
        return values[self.index]

    def memory(self):
        return {"total": 1000, "available": 250, "percent": 75.0}

    def disks(self):
        return [{"root": "C:\\", "total": 100, "used": 40, "free": 60, "percent": 40.0}]

    def processes(self):
        values = (
            [{"pid": 10, "name": "one.exe", "threads": 2, "memory_bytes": 100, "cpu_time_seconds": 1.0}],
            [{"pid": 10, "name": "one.exe", "threads": 2, "memory_bytes": 120, "cpu_time_seconds": 3.0}],
        )
        result = values[self.index]
        self.index += 1
        return result

    def terminate(self, pid):
        self.terminated.append(pid)


class SystemCollectorTest(unittest.TestCase):
    def test_collector_uses_elapsed_deltas_for_cpu(self):
        backend = FakeBackend()
        clocks = iter((10.0, 12.0))
        collector = SystemCollector(
            backend=backend,
            clock=lambda: next(clocks),
            cpu_count=4,
        )

        first = collector.collect()
        second = collector.collect()

        self.assertEqual(first["cpu_percent"], 0.0)
        self.assertAlmostEqual(second["cpu_percent"], 90.0)
        self.assertAlmostEqual(second["processes"][0]["cpu_percent"], 25.0)
        self.assertEqual(second["memory"]["used"], 750)

    def test_terminate_protects_system_and_host_processes(self):
        backend = FakeBackend()
        collector = SystemCollector(backend=backend)

        with self.assertRaises(ValueError):
            collector.terminate(4)
        with self.assertRaises(ValueError):
            collector.terminate(os.getpid())
        collector.terminate(99)

        self.assertEqual(backend.terminated, [99])


if __name__ == "__main__":
    unittest.main()
