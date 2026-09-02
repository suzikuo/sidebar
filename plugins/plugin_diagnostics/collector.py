from __future__ import annotations

import ctypes
import gc
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from core.logger import logger


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
LOG_TAIL_BYTES = 256 * 1024


class FILETIME(ctypes.Structure):
    _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
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
        ("private_usage", ctypes.c_size_t),
    )


def _filetime_seconds(value):
    return (((int(value.high) << 32) | int(value.low)) / 10_000_000.0)


class WindowsProcessBackend:
    def __init__(self):
        if os.name != "nt":
            raise OSError("插件诊断仅支持 Windows。")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self.psapi.GetProcessMemoryInfo.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
            wintypes.DWORD,
        )
        self.kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
            ctypes.POINTER(FILETIME),
        )
        self.kernel32.GetProcessHandleCount.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )

    def sample(self):
        handle = self.kernel32.GetCurrentProcess()
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.size = ctypes.sizeof(counters)
        if not self.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.size
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        created = FILETIME()
        exited = FILETIME()
        kernel = FILETIME()
        user = FILETIME()
        if not self.kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        handles = wintypes.DWORD()
        if not self.kernel32.GetProcessHandleCount(handle, ctypes.byref(handles)):
            handles.value = 0
        return {
            "cpu_time": _filetime_seconds(kernel) + _filetime_seconds(user),
            "working_set": int(counters.working_set),
            "private_bytes": int(counters.private_usage),
            "handles": int(handles.value),
        }


class DiagnosticCollector:
    def __init__(self, backend=None, clock=time.monotonic, cpu_count=None, modules=None):
        self.backend = backend or WindowsProcessBackend()
        self.clock = clock
        self.cpu_count = max(1, int(cpu_count or os.cpu_count() or 1))
        self.modules = modules if modules is not None else sys.modules
        self._previous_cpu_time = None
        self._previous_clock = None

    def collect(self):
        now = float(self.clock())
        process = self.backend.sample()
        cpu_percent = 0.0
        if self._previous_cpu_time is not None and self._previous_clock is not None:
            elapsed = max(0.001, now - self._previous_clock)
            cpu_percent = max(
                0.0,
                min(
                    100.0,
                    (process["cpu_time"] - self._previous_cpu_time)
                    / elapsed
                    / self.cpu_count
                    * 100.0,
                ),
            )
        self._previous_cpu_time = process["cpu_time"]
        self._previous_clock = now
        process["cpu_percent"] = cpu_percent
        process["threads"] = len(threading.enumerate())
        process["python_objects"] = len(gc.get_objects())
        process["gc_counts"] = list(gc.get_count())
        process["loaded_modules"] = len(self.modules)
        return {
            "process": process,
            "plugins": collect_loaded_plugins(self.modules),
            "errors": read_error_log_tail(logger),
            "timestamp": int(time.time()),
        }


def collect_loaded_plugins(modules=None):
    modules = modules if modules is not None else sys.modules
    prefixes = sorted(
        {
            name.split(".", 1)[0]
            for name in modules
            if name.startswith("_agiletiles_plugin_")
        }
    )
    plugins = []
    for prefix in prefixes:
        package = modules.get(prefix)
        search_paths = list(getattr(package, "__path__", ()) or ())
        if not search_paths:
            continue
        root = Path(search_paths[0])
        try:
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            manifest = {}
        plugins.append(
            {
                "id": str(manifest.get("id") or prefix),
                "name": str(manifest.get("name") or manifest.get("id") or prefix),
                "version": str(manifest.get("version") or "--"),
                "modules": sum(
                    1
                    for module_name in modules
                    if module_name == prefix or module_name.startswith(f"{prefix}.")
                ),
                "path": str(root),
            }
        )
    return sorted(plugins, key=lambda item: item["id"].casefold())


def read_error_log_tail(logger_object, max_lines=80):
    paths = [
        Path(handler.baseFilename)
        for handler in getattr(logger_object, "handlers", ())
        if getattr(handler, "baseFilename", None)
    ]
    if not paths:
        return []
    path = paths[0]
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - LOG_TAIL_BYTES))
            payload = handle.read()
    except OSError:
        return []
    lines = payload.decode("utf-8", errors="replace").splitlines()
    return [line for line in lines if line.strip()][-max(1, int(max_lines)) :]


__all__ = [
    "DiagnosticCollector",
    "WindowsProcessBackend",
    "collect_loaded_plugins",
    "read_error_log_tail",
]
