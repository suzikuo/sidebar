"""Check whether v2rayN's Xray Metrics endpoint reports proxy traffic."""

from __future__ import annotations

import argparse
import sys
import time

from builtin_plugins.network_monitor.monitor import TrafficRateSampler
from builtin_plugins.network_monitor.v2ray import (
    V2RayNMetricsClient,
    V2RayNMetricsConfig,
    V2RayNMetricsError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="检查 v2rayN/Xray HTTP Metrics 中的代理流量。",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Metrics 地址")
    parser.add_argument(
        "--port",
        type=int,
        default=21193,
        help="Metrics 端口，通常是 v2rayN 本地混合端口 + 4",
    )
    parser.add_argument("--timeout", type=float, default=1.5, help="单次请求超时（秒）")
    parser.add_argument("--interval", type=float, default=1.0, help="采样间隔（秒）")
    parser.add_argument("--count", type=int, default=10, help="采样次数")
    return parser


def run_monitor(
    client,
    *,
    interval: float,
    count: int,
    stream=sys.stdout,
    clock=time.monotonic,
    sleep=time.sleep,
) -> bool:
    sampler = TrafficRateSampler()
    changed = False
    for index in range(count):
        counters = client.read_counters()
        rates = sampler.sample(counters, now=clock())
        print(
            f"[{index + 1:02d}/{count:02d}] "
            f"累计 ↑ {counters.upload_bytes:,} B  "
            f"↓ {counters.download_bytes:,} B  |  "
            f"实时 ↑ {_format_rate(rates.upload_bytes_per_second)}  "
            f"↓ {_format_rate(rates.download_bytes_per_second)}",
            file=stream,
        )
        if rates.upload_bytes_per_second > 0 or rates.download_bytes_per_second > 0:
            changed = True
        if index + 1 < count:
            sleep(interval)
    return changed


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.interval <= 0:
        print("错误：采样间隔必须大于 0。", file=sys.stderr)
        return 2
    if args.count < 2:
        print("错误：至少需要采样 2 次才能计算实时速度。", file=sys.stderr)
        return 2
    try:
        config = V2RayNMetricsConfig(
            host=args.host,
            port=args.port,
            timeout_seconds=args.timeout,
        )
        print(f"正在读取 {config.endpoint}")
        changed = run_monitor(
            V2RayNMetricsClient(config),
            interval=args.interval,
            count=args.count,
        )
    except (ValueError, V2RayNMetricsError) as error:
        print(f"读取失败：{error}", file=sys.stderr)
        return 1

    if changed:
        print("结论：已取得 v2rayN 代理累计流量，并检测到实时流量变化。")
    else:
        print("结论：已取得 v2rayN 代理累计流量，但采样期间没有检测到变化。")
    return 0


def _format_rate(value: float) -> str:
    value = max(0.0, float(value))
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if value < 1024.0 or unit == "GB/s":
            if unit == "B/s":
                return f"{value:.0f} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return "0 B/s"


if __name__ == "__main__":
    raise SystemExit(main())
