"""Pure collection and configuration logic for network traffic snapshots."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .models import ApplicationTraffic
from .monitor import TrafficRates, TrafficRateSampler, WindowsNetworkMonitor


DEFAULT_CONFIG = {
    "application_monitor_enabled": False,
    "network_scope": "default_route",
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
    "floating_layout_mode": "single",
    "floating_scale": 100,
    "floating_font_size": 11,
    "floating_display_mode": "proxy_direct",
    "floating_show_v2ray_metadata": False,
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
    applications: tuple[ApplicationTraffic, ...] = ()
    app_monitor_available: bool = False
    app_monitor_error: str | None = None
    timestamp: int = 0
    interval_seconds: float = 1.0
    v2ray_node: str | None = None
    v2ray_latency_ms: float | None = None
    v2ray_route: str | None = None


def normalize_config(value: Mapping | None) -> dict:
    source = value if isinstance(value, Mapping) else {}
    config = dict(DEFAULT_CONFIG)
    config["application_monitor_enabled"] = bool(
        source.get("application_monitor_enabled", False)
    )
    network_scope = str(source.get("network_scope", "default_route")).strip().lower()
    config["network_scope"] = (
        network_scope if network_scope in {"default_route", "all_active"} else "default_route"
    )
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
    layout_mode = str(source.get("floating_layout_mode", "single")).strip().lower()
    config["floating_layout_mode"] = (
        layout_mode if layout_mode in {"single", "double"} else "single"
    )
    config["floating_scale"] = _bounded_int(
        source.get("floating_scale"),
        DEFAULT_CONFIG["floating_scale"],
        70,
        140,
    )
    config["floating_font_size"] = _bounded_int(
        source.get("floating_font_size"),
        DEFAULT_CONFIG["floating_font_size"],
        8,
        18,
    )
    display_mode = str(
        source.get("floating_display_mode", "proxy_direct")
    ).strip().lower()
    allowed_modes = {
        "proxy_direct",
        "system_direct",
        "system_proxy",
        "system_proxy_direct",
    }
    config["floating_display_mode"] = (
        display_mode if display_mode in allowed_modes else "proxy_direct"
    )
    config["floating_show_v2ray_metadata"] = bool(
        source.get("floating_show_v2ray_metadata", False)
    )
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
    if config["v2rayn_enabled"]:
        from .v2ray_source import validate_config as validate_v2ray_config

        validate_v2ray_config(
            {
                "enabled": True,
                "host": config["v2rayn_host"],
                "metrics_port": config["v2rayn_metrics_port"],
                "refresh_interval_ms": config["refresh_interval_ms"],
                "timeout_ms": config["timeout_ms"],
            }
        )
    return config


class NetworkMonitorCollector:
    """Collect one coherent system/proxy/direct rate snapshot."""

    def __init__(
        self,
        system_monitor=None,
        application_source=None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._system_monitor = system_monitor or WindowsNetworkMonitor()
        self._application_source = application_source
        self._clock = clock
        self._wall_clock = wall_clock
        self._system_sampler = TrafficRateSampler()
        self._previous_collect_time = None

    def collect(self, value: Mapping | None, proxy_snapshot=None) -> NetworkSnapshot:
        config = normalize_config(value)
        timestamp = self._clock()
        wall_timestamp = int(self._wall_clock())
        previous_collect_time = self._previous_collect_time
        self._previous_collect_time = timestamp
        interval_seconds = (
            max(0.001, timestamp - previous_collect_time)
            if previous_collect_time is not None and timestamp > previous_collect_time
            else max(0.001, config["refresh_interval_ms"] / 1000.0)
        )
        application_result = self._collect_applications(
            interval_seconds,
            config["application_monitor_enabled"],
        )
        system_rates = None
        system_error = None
        try:
            system_rates = self._system_sampler.sample(
                self._system_monitor.read_counters(config["network_scope"]),
                now=timestamp,
            )
        except Exception as error:
            system_error = str(error)

        if isinstance(proxy_snapshot, Mapping) and not proxy_snapshot.get(
            "enabled", True
        ):
            proxy_rates = TrafficRates(0.0, 0.0)
            return NetworkSnapshot(
                system=system_rates,
                proxy=proxy_rates,
                direct=system_rates,
                v2rayn_enabled=False,
                v2rayn_connected=False,
                system_error=system_error,
                applications=application_result.applications,
                app_monitor_available=application_result.available,
                app_monitor_error=application_result.error,
                timestamp=wall_timestamp,
                interval_seconds=interval_seconds,
            )

        proxy_rates, proxy_error = _external_proxy_rates(
            proxy_snapshot,
            wall_timestamp,
        )
        v2rayn_enabled = bool(
            proxy_snapshot.get("enabled", True)
            if isinstance(proxy_snapshot, Mapping)
            else True
        )
        v2rayn_connected = bool(
            proxy_snapshot.get("connected", False)
            if isinstance(proxy_snapshot, Mapping)
            else False
        )

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
            v2rayn_enabled=v2rayn_enabled,
            v2rayn_connected=v2rayn_connected and proxy_rates is not None,
            system_error=system_error,
            proxy_error=proxy_error,
            applications=application_result.applications,
            app_monitor_available=application_result.available,
            app_monitor_error=application_result.error,
            timestamp=wall_timestamp,
            interval_seconds=interval_seconds,
            v2ray_node=(
                proxy_snapshot.get("node")
                if isinstance(proxy_snapshot, Mapping)
                else None
            ),
            v2ray_latency_ms=(
                proxy_snapshot.get("latencyMs")
                if isinstance(proxy_snapshot, Mapping)
                else None
            ),
            v2ray_route=(
                proxy_snapshot.get("route")
                if isinstance(proxy_snapshot, Mapping)
                else None
            ),
        )

    def _collect_applications(self, interval_seconds, enabled):
        from .models import ApplicationTrafficResult

        if not enabled:
            return ApplicationTrafficResult((), False, "应用流量监控已关闭。")
        if self._application_source is None:
            return ApplicationTrafficResult(
                (),
                False,
                "ETW 应用流量源未配置。",
            )
        return self._application_source.drain(interval_seconds)


def _external_proxy_rates(snapshot, now):
    if not isinstance(snapshot, Mapping):
        return None, "等待独立 V2Ray 监控插件数据。"
    event_time = snapshot.get("timestamp")
    try:
        if event_time is None or now - int(event_time) > 10:
            return None, "V2Ray 实时状态已过期。"
    except (TypeError, ValueError):
        return None, "V2Ray 实时状态时间戳无效。"
    if not snapshot.get("connected"):
        return None, str(snapshot.get("error") or "V2Ray Metrics 未连接。")
    try:
        upload = max(0.0, float(snapshot["uploadSpeed"]))
        download = max(0.0, float(snapshot["downloadSpeed"]))
    except (KeyError, TypeError, ValueError):
        return None, "V2Ray 实时速率格式无效。"
    return TrafficRates(upload, download), None


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
