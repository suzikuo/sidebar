"""v2rayN/Xray HTTP Metrics client for cumulative proxy traffic."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .monitor import TrafficCounters


MAX_METRICS_RESPONSE_SIZE = 4 * 1024 * 1024


class V2RayNMetricsError(RuntimeError):
    """Raised when v2rayN's Xray Metrics endpoint is unavailable or invalid."""


@dataclass(frozen=True)
class V2RayNMetricsConfig:
    host: str = "127.0.0.1"
    port: int = 21193
    timeout_seconds: float = 0.8

    def __post_init__(self):
        host = str(self.host or "").strip().strip("[]")
        if not _is_loopback_host(host):
            raise ValueError("v2rayN Metrics 地址必须是 loopback 地址。")
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("v2rayN Metrics 端口必须在 1 到 65535 之间。")
        if float(self.timeout_seconds) <= 0:
            raise ValueError("v2rayN Metrics 查询超时必须大于 0。")
        object.__setattr__(self, "host", host)

    @property
    def endpoint(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}/debug/vars"


class V2RayNMetricsClient:
    """Read proxy cumulative counters from v2rayN's Xray /debug/vars."""

    def __init__(self, config: V2RayNMetricsConfig, opener=None):
        self._config = config
        self._opener = opener or urlopen

    def read_counters(self) -> TrafficCounters:
        request = Request(
            self._config.endpoint,
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with self._opener(
                request,
                timeout=self._config.timeout_seconds,
            ) as response:
                payload = response.read(MAX_METRICS_RESPONSE_SIZE + 1)
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            reason = getattr(error, "reason", None) or str(error)
            raise V2RayNMetricsError(
                f"无法读取 v2rayN Metrics：{reason}"
            ) from error
        if len(payload) > MAX_METRICS_RESPONSE_SIZE:
            raise V2RayNMetricsError("v2rayN Metrics 响应超过大小限制。")
        try:
            metrics = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise V2RayNMetricsError("v2rayN Metrics 返回的不是有效 JSON。") from error
        return parse_proxy_counters(metrics)


def parse_proxy_counters(metrics) -> TrafficCounters:
    if not isinstance(metrics, Mapping):
        raise V2RayNMetricsError("v2rayN Metrics 根节点必须是对象。")
    stats = metrics.get("stats")
    outbound = stats.get("outbound") if isinstance(stats, Mapping) else None
    if not isinstance(outbound, Mapping):
        raise V2RayNMetricsError("v2rayN Metrics 缺少 stats.outbound。")

    upload = 0
    download = 0
    matched = False
    for raw_tag, raw_counters in outbound.items():
        tag = str(raw_tag or "")
        if not tag.casefold().startswith("proxy"):
            continue
        if not isinstance(raw_counters, Mapping):
            raise V2RayNMetricsError(f"proxy 出站统计格式无效：{tag}")
        upload += _counter_value(raw_counters.get("uplink"), tag, "uplink")
        download += _counter_value(raw_counters.get("downlink"), tag, "downlink")
        matched = True
    if not matched:
        raise V2RayNMetricsError("v2rayN Metrics 中没有 proxy 出站统计。")
    return TrafficCounters(upload_bytes=upload, download_bytes=download)


def _counter_value(value, tag: str, direction: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V2RayNMetricsError(f"{tag}.{direction} 不是有效累计字节数。")
    parsed = int(value)
    if parsed < 0:
        raise V2RayNMetricsError(f"{tag}.{direction} 不能为负数。")
    return parsed


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


__all__ = [
    "V2RayNMetricsClient",
    "V2RayNMetricsConfig",
    "V2RayNMetricsError",
    "parse_proxy_counters",
]
