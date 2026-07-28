"""Source-neutral models shared by live collection, history, and UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NetworkConnection:
    protocol: str
    local_address: str
    local_port: int
    remote_address: str
    remote_port: int
    state: int


@dataclass(frozen=True)
class ApplicationTraffic:
    pid: int
    process_name: str
    app_path: str
    app_key: str
    upload_bytes: int
    download_bytes: int
    upload_speed: float
    download_speed: float
    connections: tuple[NetworkConnection, ...] = ()

    @property
    def connection_count(self) -> int:
        return len(self.connections)

    @property
    def total_speed(self) -> float:
        return self.upload_speed + self.download_speed


@dataclass(frozen=True)
class ApplicationTrafficResult:
    applications: tuple[ApplicationTraffic, ...]
    available: bool
    error: str | None = None
    events_lost: int = 0


@dataclass(frozen=True)
class TrafficRecord:
    timestamp: int
    source: str
    app_key: str
    app_name: str
    app_path: str
    pid: int
    upload_bytes: int
    download_bytes: int
    peak_upload_bps: float
    peak_download_bps: float
    sample_count: int = 1


@dataclass(frozen=True)
class TrafficHistoryPoint:
    timestamp: int
    upload_bytes: int
    download_bytes: int


@dataclass(frozen=True)
class TrafficRankingItem:
    app_key: str
    app_name: str
    app_path: str
    upload_bytes: int
    download_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.upload_bytes + self.download_bytes


@dataclass(frozen=True)
class TrafficHistoryResult:
    range_key: str
    source: str
    resolution: str
    started_at: int
    ended_at: int
    points: tuple[TrafficHistoryPoint, ...]
    ranking: tuple[TrafficRankingItem, ...]
    total_upload_bytes: int
    total_download_bytes: int


__all__ = [
    "ApplicationTraffic",
    "ApplicationTrafficResult",
    "NetworkConnection",
    "TrafficRecord",
    "TrafficHistoryPoint",
    "TrafficHistoryResult",
    "TrafficRankingItem",
]
