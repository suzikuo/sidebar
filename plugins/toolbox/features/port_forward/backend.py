import ipaddress
import os
import re
import subprocess
from typing import Dict, List

from core.logger import logger


_HOSTNAME_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_ELEVATED_NETSH_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try {
    $process = Start-Process `
        -FilePath 'netsh.exe' `
        -ArgumentList $env:AGILETILES_NETSH_ARGS `
        -Verb RunAs `
        -Wait `
        -PassThru `
        -WindowStyle Hidden
    exit $process.ExitCode
} catch {
    exit 1
}
"""


def _normalize_port(value, field_name: str) -> str:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number between 1 and 65535.") from exc

    if not 1 <= port <= 65535:
        raise ValueError(f"{field_name} must be between 1 and 65535.")
    return str(port)


def _normalize_ipv4(value, field_name: str) -> str:
    try:
        return str(ipaddress.IPv4Address(str(value).strip()))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{field_name} must be a valid IPv4 address.") from exc


def _normalize_target(value) -> str:
    target = str(value).strip().rstrip(".")
    if not target:
        raise ValueError("Connect address is required.")

    try:
        return str(ipaddress.IPv4Address(target))
    except ipaddress.AddressValueError:
        pass

    if len(target) > 253:
        raise ValueError("Connect address is too long.")

    labels = target.split(".")
    if any(not _HOSTNAME_LABEL.fullmatch(label) for label in labels):
        raise ValueError("Connect address must be a valid IPv4 address or hostname.")
    return target.lower()


def validate_proxy_rule(
    listen_address, listen_port, connect_address, connect_port
) -> Dict[str, str]:
    """Validate and normalize a v4-to-v4 port forwarding rule."""
    return {
        "listen_address": _normalize_ipv4(listen_address, "Listen address"),
        "listen_port": _normalize_port(listen_port, "Listen port"),
        "connect_address": _normalize_target(connect_address),
        "connect_port": _normalize_port(connect_port, "Connect port"),
    }


def _run_elevated_netsh(arguments: List[str]) -> bool:
    env = os.environ.copy()
    env["AGILETILES_NETSH_ARGS"] = subprocess.list2cmdline(arguments)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _ELEVATED_NETSH_SCRIPT,
            ],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            env=env,
            check=False,
        )
    except OSError as exc:
        logger.error("Failed to start elevated netsh command: %s", exc, exc_info=True)
        return False

    if result.returncode != 0:
        error = (result.stderr or result.stdout or "UAC request cancelled").strip()
        logger.error("Elevated netsh command failed: %s", error)
        return False
    return True


def get_proxies() -> List[Dict[str, str]]:
    """Return all configured Windows v4-to-v4 port forwarding rules."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["netsh", "interface", "portproxy", "show", "all"],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            check=False,
        )
    except OSError as exc:
        logger.error("Failed to query port forwarding rules: %s", exc, exc_info=True)
        return []

    if result.returncode != 0:
        logger.error("netsh query failed: %s", (result.stderr or "").strip())
        return []

    rules = []
    for line in result.stdout.splitlines():
        tokens = line.strip().split()
        if len(tokens) == 4 and tokens[1].isdigit() and tokens[3].isdigit():
            rules.append(
                {
                    "listen_address": tokens[0],
                    "listen_port": tokens[1],
                    "connect_address": tokens[2],
                    "connect_port": tokens[3],
                }
            )
    return rules


def add_proxy(
    listen_address: str, listen_port: str, connect_address: str, connect_port: str
) -> bool:
    """Add or replace a validated port forwarding rule with UAC elevation."""
    try:
        rule = validate_proxy_rule(
            listen_address, listen_port, connect_address, connect_port
        )
    except ValueError as exc:
        logger.warning("Invalid port forwarding rule: %s", exc)
        return False

    return _run_elevated_netsh(
        [
            "interface",
            "portproxy",
            "add",
            "v4tov4",
            f"listenport={rule['listen_port']}",
            f"listenaddress={rule['listen_address']}",
            f"connectport={rule['connect_port']}",
            f"connectaddress={rule['connect_address']}",
        ]
    )


def delete_proxy(listen_address: str, listen_port: str) -> bool:
    """Delete a validated port forwarding rule with UAC elevation."""
    try:
        address = _normalize_ipv4(listen_address, "Listen address")
        port = _normalize_port(listen_port, "Listen port")
    except ValueError as exc:
        logger.warning("Invalid port forwarding rule identity: %s", exc)
        return False

    return _run_elevated_netsh(
        [
            "interface",
            "portproxy",
            "delete",
            "v4tov4",
            f"listenport={port}",
            f"listenaddress={address}",
        ]
    )
