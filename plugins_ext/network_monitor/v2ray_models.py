"""V2Ray traffic and status models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TrafficCounters:
    upload_bytes: int
    download_bytes: int


@dataclass(frozen=True)
class TrafficRates:
    upload_bytes_per_second: float
    download_bytes_per_second: float


@dataclass(frozen=True)
class V2RaySnapshot:
    rates: TrafficRates | None
    enabled: bool
    connected: bool
    timestamp: int
    interval_seconds: float
    error: str | None = None
    node_name: str | None = None
    latency_ms: float | None = None
    route_name: str | None = None


__all__ = ["TrafficCounters", "TrafficRates", "V2RaySnapshot"]
