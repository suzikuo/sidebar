import os
import subprocess
import sys
import unittest

from core.process_control import (
    ProcessControlError,
    WAIT_FOR_PID_FLAG,
    build_restart_command,
    extract_wait_for_pid,
    wait_for_process_exit,
)


class ProcessControlTest(unittest.TestCase):
    def test_extract_wait_pid_removes_private_arguments(self):
        process_id, cleaned = extract_wait_for_pid(
            ["main.py", "--mode", "compact", WAIT_FOR_PID_FLAG, "123"]
        )

        self.assertEqual(process_id, 123)
        self.assertEqual(cleaned, ["main.py", "--mode", "compact"])

    def test_extract_wait_pid_rejects_invalid_protocol(self):
        invalid_vectors = [
            ["main.py", WAIT_FOR_PID_FLAG],
            ["main.py", WAIT_FOR_PID_FLAG, "not-a-pid"],
            ["main.py", WAIT_FOR_PID_FLAG, "0"],
            [
                "main.py",
                WAIT_FOR_PID_FLAG,
                "1",
                WAIT_FOR_PID_FLAG,
                "2",
            ],
        ]
        for argv in invalid_vectors:
            with self.subTest(argv=argv):
                with self.assertRaises(ProcessControlError) as invalid:
                    extract_wait_for_pid(argv)
                self.assertEqual(invalid.exception.code, "INVALID_WAIT_PID")

    def test_restart_command_handles_source_and_frozen_entrypoints(self):
        source = build_restart_command(
            "python.exe", ["main.py", "--debug"], 42, frozen=False
        )
        frozen = build_restart_command(
            "AgileTiles.exe", ["AgileTiles.exe", "--debug"], 42, frozen=True
        )

        self.assertEqual(
            source,
            ["python.exe", "main.py", "--debug", WAIT_FOR_PID_FLAG, "42"],
        )
        self.assertEqual(
            frozen,
            ["AgileTiles.exe", "--debug", WAIT_FOR_PID_FLAG, "42"],
        )

    def test_wait_gate_blocks_until_child_process_exits(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.15)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(lambda: child.poll() is None and child.kill())

        self.assertTrue(wait_for_process_exit(child.pid, timeout_seconds=5.0))
        child.wait(timeout=5.0)

    def test_wait_gate_times_out_for_current_process(self):
        self.assertFalse(wait_for_process_exit(os.getpid(), timeout_seconds=0.01))


if __name__ == "__main__":
    unittest.main()
