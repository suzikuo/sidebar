"""Best-effort Windows ETW application traffic collection."""

from __future__ import annotations

import ctypes
import os
import socket
import struct
import sys
import threading
import time
from collections import defaultdict
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Mapping

from .models import (
    ApplicationTraffic,
    ApplicationTrafficResult,
    NetworkConnection,
)


KERNEL_NETWORK_PROVIDER = "{7DD42A49-5329-4832-8DFD-43D979153A88}"
KERNEL_NETWORK_KEYWORDS = 0x10 | 0x20
UPLOAD_EVENT_IDS = frozenset((10, 26, 42, 58))
DOWNLOAD_EVENT_IDS = frozenset((11, 27, 43, 59))
TRAFFIC_EVENT_IDS = UPLOAD_EVENT_IDS | DOWNLOAD_EVENT_IDS

AF_INET = 2
AF_INET6 = 23
TCP_TABLE_OWNER_PID_ALL = 5
ERROR_INSUFFICIENT_BUFFER = 122
NO_ERROR = 0
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class ApplicationMonitorError(RuntimeError):
    """Raised when application-level collection cannot start."""


@dataclass(frozen=True)
class _ProcessIdentity:
    name: str
    path: str


class _MibTcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("state", wintypes.DWORD),
        ("local_address", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("remote_address", wintypes.DWORD),
        ("remote_port", wintypes.DWORD),
        ("pid", wintypes.DWORD),
    ]


class _MibTcp6RowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("local_address", ctypes.c_ubyte * 16),
        ("local_scope_id", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("remote_address", ctypes.c_ubyte * 16),
        ("remote_scope_id", wintypes.DWORD),
        ("remote_port", wintypes.DWORD),
        ("state", wintypes.DWORD),
        ("pid", wintypes.DWORD),
    ]


class WindowsProcessResolver:
    """Resolve process image paths with a small TTL cache."""

    def __init__(
        self,
        cache_ttl_seconds=30.0,
        max_cache_entries=512,
        clock=time.monotonic,
    ):
        self._cache_ttl = float(cache_ttl_seconds)
        self._max_cache_entries = max(1, int(max_cache_entries))
        self._clock = clock
        self._cache = {}
        self._kernel32 = None
        if sys.platform == "win32":
            self._kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
            self._kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            self._kernel32.OpenProcess.restype = wintypes.HANDLE
            self._kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._kernel32.CloseHandle.restype = wintypes.BOOL

    def resolve(self, pid: int) -> _ProcessIdentity:
        pid = max(0, int(pid))
        now = self._clock()
        cached = self._cache.get(pid)
        if cached is not None and cached[0] > now:
            return cached[1]
        identity = self._query(pid)
        self._cache[pid] = (now + self._cache_ttl, identity)
        self._trim_cache(now)
        return identity

    def clear(self):
        self._cache.clear()

    def _trim_cache(self, now):
        if len(self._cache) <= self._max_cache_entries:
            return
        for cached_pid, (expires_at, _identity) in tuple(self._cache.items()):
            if expires_at <= now:
                del self._cache[cached_pid]
        while len(self._cache) > self._max_cache_entries:
            self._cache.pop(next(iter(self._cache)))

    def _query(self, pid: int) -> _ProcessIdentity:
        if pid == 0:
            return _ProcessIdentity("System", "")
        if self._kernel32 is None:
            return _ProcessIdentity(f"PID {pid}", "")
        handle = self._kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not handle:
            return _ProcessIdentity(f"PID {pid}", "")
        try:
            capacity = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            if not self._kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(capacity),
            ):
                return _ProcessIdentity(f"PID {pid}", "")
            path = buffer.value
            return _ProcessIdentity(os.path.basename(path) or f"PID {pid}", path)
        finally:
            self._kernel32.CloseHandle(handle)


class WindowsTcpConnectionReader:
    """Read current TCP v4/v6 owner-PID tables using IP Helper API."""

    def __init__(self, get_extended_tcp_table=None):
        if get_extended_tcp_table is None:
            if sys.platform != "win32":
                self._get_table = None
                return
            iphlpapi = ctypes.WinDLL("iphlpapi.dll")
            get_extended_tcp_table = iphlpapi.GetExtendedTcpTable
            get_extended_tcp_table.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.DWORD),
                wintypes.BOOL,
                wintypes.ULONG,
                wintypes.ULONG,
                wintypes.ULONG,
            ]
            get_extended_tcp_table.restype = wintypes.DWORD
        self._get_table = get_extended_tcp_table

    def read_by_pid(self) -> dict[int, tuple[NetworkConnection, ...]]:
        if self._get_table is None:
            return {}
        grouped = defaultdict(list)
        for family, row_type in (
            (AF_INET, _MibTcpRowOwnerPid),
            (AF_INET6, _MibTcp6RowOwnerPid),
        ):
            for pid, connection in self._read_family(family, row_type):
                grouped[pid].append(connection)
        return {pid: tuple(items) for pid, items in grouped.items()}

    def _read_family(self, family, row_type):
        size = wintypes.DWORD(0)
        result = self._get_table(
            None,
            ctypes.byref(size),
            False,
            family,
            TCP_TABLE_OWNER_PID_ALL,
            0,
        )
        if result not in (NO_ERROR, ERROR_INSUFFICIENT_BUFFER):
            return ()
        buffer = ctypes.create_string_buffer(max(size.value, ctypes.sizeof(wintypes.DWORD)))
        result = self._get_table(
            buffer,
            ctypes.byref(size),
            False,
            family,
            TCP_TABLE_OWNER_PID_ALL,
            0,
        )
        if result != NO_ERROR:
            return ()
        count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
        if count <= 0:
            return ()
        rows = (row_type * count).from_buffer(buffer, ctypes.sizeof(wintypes.DWORD))
        return tuple(self._convert_row(family, row) for row in rows)

    @staticmethod
    def _convert_row(family, row):
        if family == AF_INET:
            local_address = socket.inet_ntoa(struct.pack("<L", row.local_address))
            remote_address = socket.inet_ntoa(struct.pack("<L", row.remote_address))
        else:
            local_address = socket.inet_ntop(socket.AF_INET6, bytes(row.local_address))
            remote_address = socket.inet_ntop(socket.AF_INET6, bytes(row.remote_address))
        return (
            int(row.pid),
            NetworkConnection(
                protocol="TCP6" if family == AF_INET6 else "TCP4",
                local_address=local_address,
                local_port=_decode_port(row.local_port),
                remote_address=remote_address,
                remote_port=_decode_port(row.remote_port),
                state=int(row.state),
            ),
        )


class EtwApplicationTrafficSource:
    """Accumulate Kernel-Network ETW events and expose interval snapshots."""

    def __init__(
        self,
        capture_factory: Callable | None = None,
        process_resolver=None,
        connection_reader=None,
    ):
        self._capture_factory = capture_factory
        self._process_resolver = process_resolver or WindowsProcessResolver()
        self._connection_reader = connection_reader or WindowsTcpConnectionReader()
        self._lock = threading.Lock()
        self._counters = defaultdict(lambda: [0, 0])
        self._capture = None
        self._available = False
        self._error = None

    @property
    def available(self) -> bool:
        return self._available

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> bool:
        if self._capture is not None:
            return self._available
        try:
            capture = self._create_capture()
            capture.start()
        except Exception as error:
            self._capture = None
            self._available = False
            self._error = _friendly_start_error(error)
            return False
        self._capture = capture
        self._available = True
        self._error = None
        return True

    def stop(self):
        capture = self._capture
        self._capture = None
        self._available = False
        with self._lock:
            self._counters.clear()
        clear = getattr(self._process_resolver, "clear", None)
        if callable(clear):
            clear()
        if capture is not None:
            try:
                capture.stop()
            except Exception:
                pass

    def drain(self, interval_seconds: float) -> ApplicationTrafficResult:
        if not self._available:
            return ApplicationTrafficResult((), False, self._error)
        interval = max(0.001, float(interval_seconds))
        with self._lock:
            counters = dict(self._counters)
            self._counters.clear()
        try:
            connections = self._connection_reader.read_by_pid()
        except Exception:
            connections = {}
        applications = []
        for pid, (upload_bytes, download_bytes) in counters.items():
            if upload_bytes <= 0 and download_bytes <= 0:
                continue
            identity = self._process_resolver.resolve(pid)
            app_key = (identity.path or identity.name or f"pid:{pid}").casefold()
            applications.append(
                ApplicationTraffic(
                    pid=pid,
                    process_name=identity.name,
                    app_path=identity.path,
                    app_key=app_key,
                    upload_bytes=upload_bytes,
                    download_bytes=download_bytes,
                    upload_speed=upload_bytes / interval,
                    download_speed=download_bytes / interval,
                    connections=connections.get(pid, ()),
                )
            )
        applications.sort(key=lambda item: item.total_speed, reverse=True)
        return ApplicationTrafficResult(tuple(applications), True)

    def _create_capture(self):
        if self._capture_factory is not None:
            return self._capture_factory(self._on_event)
        if sys.platform != "win32":
            raise ApplicationMonitorError("ETW 应用流量采集仅支持 Windows。")
        try:
            import etw
        except ImportError as error:
            raise ApplicationMonitorError("缺少 pywintrace ETW 运行时。") from error
        provider = etw.ProviderInfo(
            "Microsoft-Windows-Kernel-Network",
            etw.GUID(KERNEL_NETWORK_PROVIDER),
            level=4,
            any_keywords=KERNEL_NETWORK_KEYWORDS,
        )
        return etw.ETW(
            session_name=f"AgileTiles-Network-{os.getpid()}",
            providers=[provider],
            event_callback=self._on_event,
            event_id_filters=sorted(TRAFFIC_EVENT_IDS),
            ignore_exists_error=False,
        )

    def _on_event(self, event):
        parsed = parse_etw_traffic_event(event)
        if parsed is None:
            return
        pid, upload_bytes, download_bytes = parsed
        with self._lock:
            counter = self._counters[pid]
            counter[0] += upload_bytes
            counter[1] += download_bytes


def parse_etw_traffic_event(event):
    """Return ``(pid, upload_bytes, download_bytes)`` for a traffic event."""
    if not isinstance(event, tuple) or len(event) != 2:
        return None
    raw_event_id, payload = event
    try:
        event_id = int(raw_event_id)
    except (TypeError, ValueError):
        return None
    if event_id not in TRAFFIC_EVENT_IDS or not isinstance(payload, Mapping):
        return None
    fields = {str(key).casefold(): value for key, value in payload.items()}
    pid = _positive_int(fields.get("pid"))
    size = _positive_int(fields.get("size"))
    header = payload.get("EventHeader")
    if pid is None and isinstance(header, Mapping):
        pid = _positive_int(header.get("ProcessId"))
    if pid is None or size is None or size <= 0:
        return None
    if event_id in UPLOAD_EVENT_IDS:
        return pid, size, 0
    return pid, 0, size


def _decode_port(value) -> int:
    return socket.ntohs(int(value) & 0xFFFF)


def _positive_int(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _friendly_start_error(error) -> str:
    message = str(error).strip() or error.__class__.__name__
    winerror = getattr(error, "winerror", None)
    if winerror == 5:
        return "ETW 权限不足；请以管理员身份运行或加入 Performance Log Users。"
    if winerror == 183:
        return "ETW 会话已存在；关闭其他同名监控实例后重试。"
    return f"ETW 启动失败：{message}"


__all__ = [
    "ApplicationMonitorError",
    "DOWNLOAD_EVENT_IDS",
    "EtwApplicationTrafficSource",
    "KERNEL_NETWORK_PROVIDER",
    "TRAFFIC_EVENT_IDS",
    "UPLOAD_EVENT_IDS",
    "WindowsProcessResolver",
    "WindowsTcpConnectionReader",
    "parse_etw_traffic_event",
]
