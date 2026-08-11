from __future__ import annotations

import ctypes
import os
import shutil
import time
from ctypes import wintypes


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class FILETIME(ctypes.Structure):
    _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = (
        ("length", wintypes.DWORD),
        ("memory_load", wintypes.DWORD),
        ("total_physical", ctypes.c_ulonglong),
        ("available_physical", ctypes.c_ulonglong),
        ("total_page_file", ctypes.c_ulonglong),
        ("available_page_file", ctypes.c_ulonglong),
        ("total_virtual", ctypes.c_ulonglong),
        ("available_virtual", ctypes.c_ulonglong),
        ("available_extended_virtual", ctypes.c_ulonglong),
    )


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = (
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("default_heap_id", ctypes.c_size_t),
        ("module_id", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent_process_id", wintypes.DWORD),
        ("base_priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("executable", wintypes.WCHAR * 260),
    )


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = (
        ("size", wintypes.DWORD),
        ("page_fault_count", wintypes.DWORD),
        ("peak_working_set", ctypes.c_size_t),
        ("working_set", ctypes.c_size_t),
        ("peak_paged_pool", ctypes.c_size_t),
        ("paged_pool", ctypes.c_size_t),
        ("peak_nonpaged_pool", ctypes.c_size_t),
        ("nonpaged_pool", ctypes.c_size_t),
        ("page_file", ctypes.c_size_t),
        ("peak_page_file", ctypes.c_size_t),
    )


def _filetime_value(value):
    return (int(value.high) << 32) | int(value.low)


class WindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise OSError("系统监控仅支持 Windows。")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel32.CreateToolhelp32Snapshot.argtypes = (
            wintypes.DWORD,
            wintypes.DWORD,
        )
        self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        self.kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        self.kernel32.OpenProcess.restype = wintypes.HANDLE
        self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.kernel32.GetSystemTimes.argtypes = (
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
        )
        self.kernel32.GlobalMemoryStatusEx.argtypes = (
            ctypes.POINTER(MEMORYSTATUSEX),
        )
        self.kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
        )
        self.kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        self.kernel32.Process32FirstW.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        )
        self.kernel32.Process32NextW.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESSENTRY32W),
        )
        self.psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        )

    def system_times(self):
        idle = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not self.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return (_filetime_value(idle), _filetime_value(kernel), _filetime_value(user))

    def memory(self):
        status = MEMORYSTATUSEX()
        status.length = ctypes.sizeof(status)
        if not self.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {
            "total": int(status.total_physical),
            "available": int(status.available_physical),
            "percent": float(status.memory_load),
        }

    def disks(self):
        mask = int(self.kernel32.GetLogicalDrives())
        disks = []
        for index in range(26):
            if not mask & (1 << index):
                continue
            root = f"{chr(65 + index)}:\\"
            if int(self.kernel32.GetDriveTypeW(root)) != 3:
                continue
            try:
                usage = shutil.disk_usage(root)
            except OSError:
                continue
            disks.append(
                {
                    "root": root,
                    "total": usage.total,
                    "used": usage.used,
                    "free": usage.free,
                    "percent": (usage.used / usage.total * 100.0) if usage.total else 0.0,
                }
            )
        return disks

    def processes(self):
        snapshot = self.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        processes = []
        try:
            entry = PROCESSENTRY32W()
            entry.size = ctypes.sizeof(entry)
            has_entry = bool(self.kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
            while has_entry:
                processes.append(self._process_entry(entry))
                has_entry = bool(
                    self.kernel32.Process32NextW(snapshot, ctypes.byref(entry))
                )
        finally:
            self.kernel32.CloseHandle(snapshot)
        return processes

    def _process_entry(self, entry):
        pid = int(entry.process_id)
        result = {
            "pid": pid,
            "name": str(entry.executable),
            "threads": int(entry.threads),
            "memory_bytes": 0,
            "cpu_time_seconds": None,
        }
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return result
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.size = ctypes.sizeof(counters)
            if self.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.size
            ):
                result["memory_bytes"] = int(counters.working_set)

            created = FILETIME()
            exited = FILETIME()
            kernel = FILETIME()
            user = FILETIME()
            if self.kernel32.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ):
                result["cpu_time_seconds"] = (
                    _filetime_value(kernel) + _filetime_value(user)
                ) / 10_000_000.0
        finally:
            self.kernel32.CloseHandle(handle)
        return result

    def terminate(self, pid):
        handle = self.kernel32.OpenProcess(PROCESS_TERMINATE, False, int(pid))
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.kernel32.TerminateProcess(handle, 1):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.kernel32.CloseHandle(handle)


class SystemCollector:
    def __init__(self, backend=None, clock=time.monotonic, cpu_count=None):
        self.backend = backend or WindowsBackend()
        self.clock = clock
        self.cpu_count = max(1, int(cpu_count or os.cpu_count() or 1))
        self._previous_system_times = None
        self._previous_process_times = {}
        self._previous_clock = None

    def collect(self):
        now = float(self.clock())
        system_times = self.backend.system_times()
        memory = self.backend.memory()
        disks = self.backend.disks()
        raw_processes = self.backend.processes()

        cpu_percent = self._system_cpu_percent(system_times)
        elapsed = None if self._previous_clock is None else max(0.001, now - self._previous_clock)
        process_times = {}
        processes = []
        for raw in raw_processes:
            process = dict(raw)
            pid = int(process["pid"])
            cpu_time = process.pop("cpu_time_seconds", None)
            process_cpu = 0.0
            if cpu_time is not None:
                process_times[pid] = float(cpu_time)
                previous = self._previous_process_times.get(pid)
                if previous is not None and elapsed is not None:
                    process_cpu = max(
                        0.0,
                        min(100.0, (float(cpu_time) - previous) / elapsed / self.cpu_count * 100.0),
                    )
            process["cpu_percent"] = process_cpu
            processes.append(process)

        self._previous_clock = now
        self._previous_process_times = process_times
        processes.sort(
            key=lambda item: (item["cpu_percent"], item.get("memory_bytes", 0)),
            reverse=True,
        )
        used_memory = max(0, int(memory["total"]) - int(memory["available"]))
        return {
            "cpu_percent": cpu_percent,
            "memory": {**memory, "used": used_memory},
            "disks": disks,
            "processes": processes,
            "process_count": len(processes),
            "timestamp": int(time.time()),
        }

    def terminate(self, pid):
        pid = int(pid)
        if pid <= 4 or pid == os.getpid():
            raise ValueError("不能结束系统关键进程或 Agile Tiles 自身进程。")
        self.backend.terminate(pid)

    def _system_cpu_percent(self, current):
        previous = self._previous_system_times
        self._previous_system_times = current
        if previous is None:
            return 0.0
        idle_delta = current[0] - previous[0]
        total_delta = (current[1] - previous[1]) + (current[2] - previous[2])
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (total_delta - idle_delta) / total_delta * 100.0))


__all__ = ["SystemCollector", "WindowsBackend"]
