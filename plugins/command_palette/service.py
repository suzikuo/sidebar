from __future__ import annotations

import os
import subprocess

from .models import DEFAULT_COMMANDS, normalize_provider_command


PROVIDERS = (
    "app_launcher",
    "bookmarks.card",
    "ssh_manager",
    "toolbox",
    "system_monitor",
    "windows_controls",
    "backup_restore",
    "plugin_diagnostics",
)


def collect_commands(context, custom_commands):
    commands = [dict(item) for item in DEFAULT_COMMANDS]
    commands.extend(dict(item) for item in custom_commands)
    for provider_id in PROVIDERS:
        response = context.invoke_api(f"plugins/{provider_id}/command-catalog", {})
        if not response.get("ok"):
            continue
        data = response.get("data")
        items = data.get("commands", []) if isinstance(data, dict) else []
        for item in items:
            normalized = normalize_provider_command(provider_id, item)
            if normalized is not None:
                commands.append(normalized)
    return commands


def execute_command(context, command):
    route = command.get("route")
    if route:
        response = context.invoke_api(route, command.get("payload") or {})
        if not response.get("ok"):
            raise RuntimeError(response.get("message") or "命令执行失败。")
        return response.get("data")

    kind = command.get("kind")
    target = str(command.get("target") or "").strip()
    if not target:
        raise ValueError("命令目标为空。")
    if kind == "uri":
        if not hasattr(os, "startfile"):
            raise OSError("当前平台不支持 URI 启动。")
        os.startfile(target)
        return {"started": True}

    arguments = [str(part) for part in command.get("arguments", [])]
    subprocess.Popen([target, *arguments], shell=False)
    return {"started": True}


__all__ = ["PROVIDERS", "collect_commands", "execute_command"]
