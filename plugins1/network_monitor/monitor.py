"""Windows interface counters and reset-safe byte-rate sampling."""

from __future__ import annotations

import ctypes
import socket
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass


NO_ERROR = 0
IF_OPER_STATUS_UP = 1
IF_TYPE_SOFTWARE_LOOPBACK = 24
IF_MAX_STRING_SIZE = 256
IF_MAX_PHYS_ADDRESS_LENGTH = 32
NETWORK_SCOPE_DEFAULT_ROUTE = "default_route"
NETWORK_SCOPE_ALL_ACTIVE = "all_active"
DEFAULT_ROUTE_PROBE_ADDRESS = "1.1.1.1"


class NetworkMonitorError(RuntimeError):
    """Raised when the Windows IP Helper API cannot provide counters."""


@dataclass(frozen=True)
class TrafficCounters:
    upload_bytes: int
    download_bytes: int


@dataclass(frozen=True)
class TrafficRates:
    upload_bytes_per_second: float
    download_bytes_per_second: float


class _NetLuid(ctypes.Union):
    _fields_ = [("Value", ctypes.c_ulonglong)]


class _Guid(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.ULONG),
        ("Data2", wintypes.USHORT),
        ("Data3", wintypes.USHORT),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _MibIfRow2(ctypes.Structure):
    _fields_ = [
        ("InterfaceLuid", _NetLuid),
        ("InterfaceIndex", wintypes.ULONG),
        ("InterfaceGuid", _Guid),
        ("Alias", wintypes.WCHAR * (IF_MAX_STRING_SIZE + 1)),
        ("Description", wintypes.WCHAR * (IF_MAX_STRING_SIZE + 1)),
        ("PhysicalAddressLength", wintypes.ULONG),
        ("PhysicalAddress", ctypes.c_ubyte * IF_MAX_PHYS_ADDRESS_LENGTH),
        ("PermanentPhysicalAddress", ctypes.c_ubyte * IF_MAX_PHYS_ADDRESS_LENGTH),
        ("Mtu", wintypes.ULONG),
        ("Type", wintypes.USHORT),
        ("TunnelType", wintypes.ULONG),
        ("MediaType", wintypes.ULONG),
        ("PhysicalMediumType", wintypes.ULONG),
        ("AccessType", wintypes.ULONG),
        ("DirectionType", wintypes.ULONG),
        ("InterfaceAndOperStatusFlags", ctypes.c_ubyte),
        ("OperStatus", wintypes.ULONG),
        ("AdminStatus", wintypes.ULONG),
        ("MediaConnectState", wintypes.ULONG),
        ("NetworkGuid", _Guid),
        ("ConnectionType", wintypes.ULONG),
        ("TransmitLinkSpeed", ctypes.c_ulonglong),
        ("ReceiveLinkSpeed", ctypes.c_ulonglong),
        ("InOctets", ctypes.c_ulonglong),
        ("InUcastPkts", ctypes.c_ulonglong),
        ("InNUcastPkts", ctypes.c_ulonglong),
        ("InDiscards", ctypes.c_ulonglong),
        ("InErrors", ctypes.c_ulonglong),
        ("InUnknownProtos", ctypes.c_ulonglong),
        ("InUcastOctets", ctypes.c_ulonglong),
        ("InMulticastOctets", ctypes.c_ulonglong),
        ("InBroadcastOctets", ctypes.c_ulonglong),
        ("OutOctets", ctypes.c_ulonglong),
        ("OutUcastPkts", ctypes.c_ulonglong),
        ("OutNUcastPkts", ctypes.c_ulonglong),
        ("OutDiscards", ctypes.c_ulonglong),
        ("OutErrors", ctypes.c_ulonglong),
        ("OutUcastOctets", ctypes.c_ulonglong),
        ("OutMulticastOctets", ctypes.c_ulonglong),
        ("OutBroadcastOctets", ctypes.c_ulonglong),
        ("OutQLen", ctypes.c_ulonglong),
    ]


class _MibIfTable2(ctypes.Structure):
    _fields_ = [
        ("NumEntries", wintypes.ULONG),
        ("Table", _MibIfRow2 * 1),
    ]


class _SockaddrIn(ctypes.Structure):
    _fields_ = [
        ("sin_family", wintypes.USHORT),
        ("sin_port", wintypes.USHORT),
        ("sin_addr", ctypes.c_ubyte * 4),
        ("sin_zero", ctypes.c_ubyte * 8),
    ]


class WindowsNetworkMonitor:
    """Read byte counters from the default-route or all active interfaces."""

    def __init__(
        self,
        get_if_table2=None,
        free_mib_table=None,
        get_best_interface_ex=None,
    ):
        if get_if_table2 is None or free_mib_table is None:
            if sys.platform != "win32":
                raise NetworkMonitorError("Windows IP Helper API is only available on Windows.")
            iphlpapi = ctypes.WinDLL("Iphlpapi.dll")
            get_if_table2 = iphlpapi.GetIfTable2
            get_if_table2.argtypes = [ctypes.POINTER(ctypes.POINTER(_MibIfTable2))]
            get_if_table2.restype = wintypes.ULONG
            free_mib_table = iphlpapi.FreeMibTable
            free_mib_table.argtypes = [ctypes.c_void_p]
            free_mib_table.restype = None
            get_best_interface_ex = iphlpapi.GetBestInterfaceEx
            get_best_interface_ex.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.DWORD),
            ]
            get_best_interface_ex.restype = wintypes.DWORD
        self._get_if_table2 = get_if_table2
        self._free_mib_table = free_mib_table
        self._get_best_interface_ex = get_best_interface_ex

    def read_counters(self, scope=NETWORK_SCOPE_DEFAULT_ROUTE) -> TrafficCounters:
        table = ctypes.POINTER(_MibIfTable2)()
        result = self._get_if_table2(ctypes.byref(table))
        if result != NO_ERROR:
            raise NetworkMonitorError(f"GetIfTable2 failed with Windows error {result}.")
        if not table:
            raise NetworkMonitorError("GetIfTable2 returned an empty table pointer.")

        try:
            count = int(table.contents.NumEntries)
            rows_address = ctypes.addressof(table.contents) + _MibIfTable2.Table.offset
            rows = (_MibIfRow2 * count).from_address(rows_address)
            interface_index = (
                self._best_default_interface_index()
                if scope == NETWORK_SCOPE_DEFAULT_ROUTE
                else None
            )
            counters, matched = self._aggregate_counters(rows, interface_index)
            if interface_index is None or matched:
                return counters
            return self._aggregate_counters(rows)[0]
        finally:
            self._free_mib_table(table)

    def _best_default_interface_index(self) -> int | None:
        if self._get_best_interface_ex is None:
            return None
        destination = _SockaddrIn()
        destination.sin_family = socket.AF_INET
        ctypes.memmove(
            destination.sin_addr,
            socket.inet_aton(DEFAULT_ROUTE_PROBE_ADDRESS),
            4,
        )
        interface_index = wintypes.DWORD(0)
        result = self._get_best_interface_ex(
            ctypes.byref(destination),
            ctypes.byref(interface_index),
        )
        if result != NO_ERROR or interface_index.value == 0:
            return None
        return int(interface_index.value)

    @classmethod
    def _aggregate_counters(cls, rows, interface_index=None):
        upload = 0
        download = 0
        matched = False
        for row in rows:
            if not cls._is_countable(row):
                continue
            if interface_index is not None and int(row.InterfaceIndex) != interface_index:
                continue
            matched = True
            upload += int(row.OutOctets)
            download += int(row.InOctets)
        return TrafficCounters(upload, download), matched

    @staticmethod
    def _is_countable(row: _MibIfRow2) -> bool:
        return row.OperStatus == IF_OPER_STATUS_UP and row.Type != IF_TYPE_SOFTWARE_LOOPBACK


class TrafficRateSampler:
    """Convert monotonic cumulative counters into reset-safe rates."""

    def __init__(self):
        self._previous_counters = None
        self._previous_time = None

    def sample(self, counters: TrafficCounters, now=None) -> TrafficRates:
        timestamp = time.monotonic() if now is None else float(now)
        previous = self._previous_counters
        previous_time = self._previous_time
        self._previous_counters = counters
        self._previous_time = timestamp

        if previous is None or previous_time is None or timestamp <= previous_time:
            return TrafficRates(0.0, 0.0)

        elapsed = timestamp - previous_time
        upload_delta = counters.upload_bytes - previous.upload_bytes
        download_delta = counters.download_bytes - previous.download_bytes
        if upload_delta < 0 or download_delta < 0:
            return TrafficRates(0.0, 0.0)
        return TrafficRates(
            upload_bytes_per_second=upload_delta / elapsed,
            download_bytes_per_second=download_delta / elapsed,
        )


__all__ = [
    "NetworkMonitorError",
    "NETWORK_SCOPE_ALL_ACTIVE",
    "NETWORK_SCOPE_DEFAULT_ROUTE",
    "TrafficCounters",
    "TrafficRates",
    "TrafficRateSampler",
    "WindowsNetworkMonitor",
]
