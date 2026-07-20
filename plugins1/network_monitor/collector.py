"""Pure collection and configuration logic for network traffic snapshots."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .monitor import TrafficRates, TrafficRateSampler, WindowsNetworkMonitor
from .v2ray import V2RayNMetricsClient, V2RayNMetricsConfig


DEFAULT_CONFIG = {
    "v2rayn_enabled": True,
    "v2rayn_host": "127.0.0.1",
    "v2rayn_metrics_port": 21193,
    "refresh_interval_ms": 1000,
    "timeout_ms": 800,
    "floating_enabled": False,
    "floating_background_color": "#202327",
    "floating_background_opacity": 0,
    "floating_font_color": "#FFFFFF",
    "floating_locked": False,
    "floating_x": None,
    "floating_y": None,
}


@dataclass(frozen=True)
class NetworkSnapshot:
    system: TrafficRates | None
    proxy: TrafficRates | None
    direct: TrafficRates | None
    v2rayn_enabled: bool
    v2rayn_connected: bool
    system_error: str | None = None
    proxy_error: str | None = None


def normalize_config(value: Mapping | None) -> dict:
    source = value if isinstance(value, Mapping) else {}
    config = dict(DEFAULT_CONFIG)
    config["v2rayn_enabled"] = bool(
        source.get("v2rayn_enabled", source.get("v2ray_enabled", True))
    )
    config["v2rayn_host"] = str(
        source.get(
            "v2rayn_host",
            source.get("v2ray_host", DEFAULT_CONFIG["v2rayn_host"]),
        )
    ).strip()
    config["v2rayn_metrics_port"] = _bounded_int(
        source.get("v2rayn_metrics_port"),
        DEFAULT_CONFIG["v2rayn_metrics_port"],
        1,
        65535,
    )
    config["refresh_interval_ms"] = _bounded_int(
        source.get("refresh_interval_ms"),
        DEFAULT_CONFIG["refresh_interval_ms"],
        500,
        10000,
    )
    config["timeout_ms"] = _bounded_int(
        source.get("timeout_ms"),
        DEFAULT_CONFIG["timeout_ms"],
        100,
        10000,
    )
    config["floating_enabled"] = bool(source.get("floating_enabled", False))
    config["floating_background_color"] = _normalize_color(
        source.get("floating_background_color"),
        DEFAULT_CONFIG["floating_background_color"],
    )
    config["floating_background_opacity"] = _bounded_int(
        source.get("floating_background_opacity"),
        DEFAULT_CONFIG["floating_background_opacity"],
        0,
        100,
    )
    config["floating_font_color"] = _normalize_color(
        source.get("floating_font_color"),
        DEFAULT_CONFIG["floating_font_color"],
    )
    config["floating_locked"] = bool(source.get("floating_locked", False))
    for key in ("floating_x", "floating_y"):
        raw_position = source.get(key)
        config[key] = (
            int(raw_position)
            if isinstance(raw_position, (int, float)) and not isinstance(raw_position, bool)
            else None
        )
    return config


def validate_config(value: Mapping | None) -> dict:
    config = normalize_config(value)
    if not config["v2rayn_host"]:
        raise ValueError("v2rayN Metrics 地址不能为空。")
    if config["v2rayn_enabled"]:
        _v2rayn_config(config)
    return config


class NetworkMonitorCollector:
    """Collect one coherent system/proxy/direct rate snapshot."""

    def __init__(
        self,
        system_monitor=None,
        v2rayn_client_factory: Callable = V2RayNMetricsClient,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._system_monitor = system_monitor or WindowsNetworkMonitor()
        self._v2rayn_client_factory = v2rayn_client_factory
        self._clock = clock
        self._system_sampler = TrafficRateSampler()
        self._proxy_sampler = TrafficRateSampler()
        self._proxy_signature = None

    def collect(self, value: Mapping | None) -> NetworkSnapshot:
        config = normalize_config(value)
        timestamp = self._clock()
        system_rates = None
        system_error = None
        try:
            system_rates = self._system_sampler.sample(
                self._system_monitor.read_counters(),
                now=timestamp,
            )
        except Exception as error:
            system_error = str(error)

        if not config["v2rayn_enabled"]:
            self._proxy_sampler = TrafficRateSampler()
            self._proxy_signature = None
            proxy_rates = TrafficRates(0.0, 0.0)
            return NetworkSnapshot(
                system=system_rates,
                proxy=proxy_rates,
                direct=system_rates,
                v2rayn_enabled=False,
                v2rayn_connected=False,
                system_error=system_error,
            )

        proxy_rates = None
        proxy_error = None
        try:
            metrics_config = _v2rayn_config(config)
            signature = (metrics_config.host, metrics_config.port)
            if signature != self._proxy_signature:
                self._proxy_sampler = TrafficRateSampler()
                self._proxy_signature = signature
            client = self._v2rayn_client_factory(metrics_config)
            proxy_rates = self._proxy_sampler.sample(
                client.read_counters(),
                now=timestamp,
            )
        except Exception as error:
            proxy_error = str(error)
            self._proxy_sampler = TrafficRateSampler()

        direct_rates = None
        if system_rates is not None and proxy_rates is not None:
            direct_rates = TrafficRates(
                upload_bytes_per_second=max(
                    0.0,
                    system_rates.upload_bytes_per_second
                    - proxy_rates.upload_bytes_per_second,
                ),
                download_bytes_per_second=max(
                    0.0,
                    system_rates.download_bytes_per_second
                    - proxy_rates.download_bytes_per_second,
                ),
            )

        return NetworkSnapshot(
            system=system_rates,
            proxy=proxy_rates,
            direct=direct_rates,
            v2rayn_enabled=True,
            v2rayn_connected=proxy_rates is not None,
            system_error=system_error,
            proxy_error=proxy_error,
        )


def _v2rayn_config(config: Mapping) -> V2RayNMetricsConfig:
    return V2RayNMetricsConfig(
        host=config["v2rayn_host"],
        port=config["v2rayn_metrics_port"],
        timeout_seconds=config["timeout_ms"] / 1000.0,
    )


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(maximum, max(minimum, parsed))


def _normalize_color(value, default: str) -> str:
    candidate = str(value or "").strip()
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", candidate):
        return candidate.upper()
    return default


__all__ = [
    "DEFAULT_CONFIG",
    "NetworkMonitorCollector",
    "NetworkSnapshot",
    "normalize_config",
    "validate_config",
]
