from __future__ import annotations

import os
import shlex
from uuid import uuid4


DEFAULT_COMMANDS = (
    {
        "id": "system.task-manager",
        "name": "任务管理器",
        "subtitle": "查看进程和系统性能",
        "category": "系统",
        "kind": "process",
        "target": "taskmgr.exe",
        "arguments": [],
    },
    {
        "id": "system.explorer",
        "name": "文件资源管理器",
        "subtitle": "打开文件资源管理器",
        "category": "系统",
        "kind": "process",
        "target": "explorer.exe",
        "arguments": [],
    },
    {
        "id": "system.settings",
        "name": "Windows 设置",
        "subtitle": "打开系统设置",
        "category": "系统",
        "kind": "uri",
        "target": "ms-settings:",
        "arguments": [],
    },
    {
        "id": "system.control-panel",
        "name": "控制面板",
        "subtitle": "打开经典控制面板",
        "category": "系统",
        "kind": "process",
        "target": "control.exe",
        "arguments": [],
    },
)


def normalize_custom_command(value):
    source = value if isinstance(value, dict) else {}
    name = str(source.get("name") or "").strip()
    target = str(source.get("target") or "").strip()
    if not name or not target:
        raise ValueError("命令名称和目标不能为空。")
    kind = str(source.get("kind") or "process").strip().lower()
    if kind not in {"process", "uri"}:
        kind = "process"
    arguments = source.get("arguments", [])
    if isinstance(arguments, str):
        arguments = _parse_arguments(arguments)
    elif isinstance(arguments, (tuple, list)):
        arguments = [str(part) for part in arguments if str(part)]
    else:
        arguments = []
    return {
        "id": str(source.get("id") or f"custom.{uuid4().hex}"),
        "name": name,
        "subtitle": str(source.get("subtitle") or target).strip(),
        "category": "自定义",
        "kind": kind,
        "target": target,
        "arguments": arguments,
        "custom": True,
    }


def normalize_provider_command(provider_id, value):
    source = value if isinstance(value, dict) else {}
    command_id = str(source.get("id") or "").strip()
    name = str(source.get("name") or "").strip()
    route = str(source.get("route") or "").strip().strip("/")
    if not command_id or not name or not route:
        return None
    return {
        "id": f"{provider_id}:{command_id}",
        "name": name,
        "subtitle": str(source.get("subtitle") or "").strip(),
        "category": str(source.get("category") or provider_id).strip(),
        "provider": provider_id,
        "route": route if "/" in route else f"plugins/{provider_id}/{route}",
        "payload": source.get("payload") if isinstance(source.get("payload"), dict) else {},
    }


def search_commands(commands, query):
    terms = [part for part in str(query or "").casefold().split() if part]
    if not terms:
        return list(commands)

    matches = []
    for index, command in enumerate(commands):
        name = str(command.get("name") or "").casefold()
        category = str(command.get("category") or "").casefold()
        subtitle = str(command.get("subtitle") or "").casefold()
        target = str(command.get("target") or "").casefold()
        arguments = " ".join(str(part) for part in command.get("arguments", ())).casefold()
        searchable = f"{name} {category} {subtitle} {target} {arguments}"
        if not all(term in searchable for term in terms):
            continue
        score = sum(
            100 if name.startswith(term) else 40 if term in name else 10
            for term in terms
        )
        matches.append((-score, index, command))
    matches.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in matches]


def _parse_arguments(value):
    text = os.path.expandvars(str(value or "")).strip()
    if not text:
        return []
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import byref, c_int

            argc = c_int()
            argv = ctypes.windll.shell32.CommandLineToArgvW(text, byref(argc))
            if argv:
                try:
                    return [argv[index] for index in range(argc.value)]
                finally:
                    ctypes.windll.kernel32.LocalFree(argv)
        except (AttributeError, OSError, TypeError, ValueError):
            pass
    return shlex.split(text, posix=True)


__all__ = [
    "DEFAULT_COMMANDS",
    "normalize_custom_command",
    "normalize_provider_command",
    "search_commands",
]
