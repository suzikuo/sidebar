"""Independent v2rayN/Xray traffic source."""

from __future__ import annotations

import ipaddress
import time
from typing import Mapping

from .v2ray import V2RayNMetricsClient, V2RayNMetricsConfig
from .v2ray_models import TrafficRates, V2RaySnapshot


DEFAULT_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "metrics_port": 21193,
    "refresh_interval_ms": 1000,
    "timeout_ms": 800,
    "show_node": False,
    "show_latency": False,
    "show_route": False,
}


class _RateSampler:
    def __init__(self):
        self._previous = None
        self._previous_time = None

    def reset(self):
        self._previous = None
        self._previous_time = None

    def sample(self, counters, now):
        previous = self._previous
        previous_time = self._previous_time
        self._previous = counters
        self._previous_time = now
        if previous is None or previous_time is None or now <= previous_time:
            return TrafficRates(0.0, 0.0), 1.0
        interval = now - previous_time
        upload = counters.upload_bytes - previous.upload_bytes
        download = counters.download_bytes - previous.download_bytes
        if upload < 0 or download < 0:
            return TrafficRates(0.0, 0.0), interval
        return TrafficRates(upload / interval, download / interval), interval


class V2RayCollector:
    def __init__(self, client_factory=V2RayNMetricsClient, clock=time.monotonic, wall_clock=time.time):
        self._client_factory = client_factory
        self._clock = clock
        self._wall_clock = wall_clock
        self._sampler = _RateSampler()
        self._signature = None

    def collect(self, value=None):
        config = validate_config(value)
        now = self._clock()
        if not config["enabled"]:
            self._sampler.reset()
            return V2RaySnapshot(
                rates=TrafficRates(0.0, 0.0),
                enabled=False,
                connected=False,
                timestamp=int(self._wall_clock()),
                interval_seconds=config["refresh_interval_ms"] / 1000.0,
            )
        metrics_config = V2RayNMetricsConfig(
            config["host"],
            config["metrics_port"],
            config["timeout_ms"] / 1000.0,
        )
        signature = (metrics_config.host, metrics_config.port)
        if signature != self._signature:
            self._sampler.reset()
            self._signature = signature
        try:
            rates, interval = self._sampler.sample(
                self._client_factory(metrics_config).read_counters(),
                now,
            )
            return V2RaySnapshot(
                rates=rates,
                enabled=True,
                connected=True,
                timestamp=int(self._wall_clock()),
                interval_seconds=interval,
            )
        except Exception as error:
            self._sampler.reset()
            return V2RaySnapshot(
                rates=None,
                enabled=True,
                connected=False,
                timestamp=int(self._wall_clock()),
                interval_seconds=config["refresh_interval_ms"] / 1000.0,
                error=str(error),
            )


def normalize_config(value=None):
    source = value if isinstance(value, Mapping) else {}
    config = dict(DEFAULT_CONFIG)
    config["enabled"] = bool(source.get("enabled", True))
    config["host"] = str(source.get("host") or DEFAULT_CONFIG["host"]).strip()
    config["metrics_port"] = _bounded_int(
        source.get("metrics_port"), DEFAULT_CONFIG["metrics_port"], 1, 65535
    )
    config["refresh_interval_ms"] = _bounded_int(
        source.get("refresh_interval_ms"), 1000, 500, 10000
    )
    config["timeout_ms"] = _bounded_int(source.get("timeout_ms"), 800, 100, 10000)
    for key in ("show_node", "show_latency", "show_route"):
        config[key] = bool(source.get(key, False))
    return config


def validate_config(value=None):
    config = normalize_config(value)
    host = config["host"].strip("[]")
    if host.lower() != "localhost":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except ValueError as error:
            raise ValueError("V2Ray Metrics 地址必须是 loopback 地址。") from error
    return config


def _bounded_int(value, default, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


__all__ = ["DEFAULT_CONFIG", "V2RayCollector", "normalize_config", "validate_config"]
