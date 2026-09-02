from __future__ import annotations

import ctypes
import os
import re
import subprocess


POWER_PLAN_PATTERN = re.compile(
    r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})\s+\((.*?)\)(\s+\*)?"
)
MEDIA_KEYS = {"mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF}
SETTINGS_URIS = {
    "display": "ms-settings:display",
    "sound": "ms-settings:sound",
    "network": "ms-settings:network",
    "bluetooth": "ms-settings:bluetooth",
    "night_light": "ms-settings:nightlight",
    "power": "ms-settings:powersleep",
}


def parse_power_plans(output):
    plans = []
    for match in POWER_PLAN_PATTERN.finditer(str(output or "")):
        plans.append(
            {
                "guid": match.group(1).lower(),
                "name": match.group(2).strip(),
                "active": bool(match.group(3)),
            }
        )
    return plans


class WindowsControlService:
    def __init__(self, runner=None, startfile=None, user32=None):
        if os.name != "nt" and runner is None:
            raise OSError("Windows 控制插件仅支持 Windows。")
        self._runner = runner or self._run
        self._startfile = startfile or getattr(os, "startfile", None)
        self._user32 = user32 or getattr(ctypes, "windll", None).user32

    def snapshot(self):
        errors = []
        try:
            brightness = self.get_brightness()
        except Exception as error:
            brightness = None
            errors.append(str(error))
        try:
            plans = self.list_power_plans()
        except Exception as error:
            plans = []
            errors.append(str(error))
        return {"brightness": brightness, "power_plans": plans, "errors": errors}

    def perform(self, action, value=None):
        if action in MEDIA_KEYS:
            self.media_key(action)
        elif action == "brightness":
            self.set_brightness(value)
        elif action == "power_plan":
            self.set_power_plan(value)
        elif action in SETTINGS_URIS:
            self.open_settings(action)
        elif action == "lock":
            if not self._user32.LockWorkStation():
                raise ctypes.WinError(ctypes.get_last_error())
        elif action == "sleep":
            self._runner(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        elif action == "restart":
            self._runner(["shutdown.exe", "/r", "/t", "0"])
        elif action == "shutdown":
            self._runner(["shutdown.exe", "/s", "/t", "0"])
        else:
            raise ValueError(f"不支持的系统操作：{action}")
        return {"action": action, "completed": True}

    def media_key(self, action):
        key = MEDIA_KEYS[action]
        self._user32.keybd_event(key, 0, 0, 0)
        self._user32.keybd_event(key, 0, 2, 0)

    def get_brightness(self):
        output = self._runner(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness | Select-Object -First 1",
            ]
        )
        match = re.search(r"\d+", output)
        if match is None:
            raise RuntimeError("当前显示器未提供亮度控制。")
        return min(100, max(0, int(match.group())))

    def set_brightness(self, value):
        brightness = min(100, max(0, int(value)))
        script = (
            "$items=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods;"
            f"$items|ForEach-Object{{Invoke-CimMethod -InputObject $_ -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={brightness}}}|Out-Null}}"
        )
        self._runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script]
        )

    def list_power_plans(self):
        return parse_power_plans(self._runner(["powercfg.exe", "/list"]))

    def set_power_plan(self, guid):
        guid = str(guid or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", guid):
            raise ValueError("电源计划 GUID 无效。")
        self._runner(["powercfg.exe", "/setactive", guid])

    def open_settings(self, page):
        if self._startfile is None:
            raise OSError("当前系统不支持设置 URI。")
        self._startfile(SETTINGS_URIS[page])

    @staticmethod
    def _run(command):
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode:
            message = (completed.stderr or completed.stdout or "系统命令执行失败").strip()
            raise RuntimeError(message)
        return completed.stdout


__all__ = [
    "MEDIA_KEYS",
    "SETTINGS_URIS",
    "WindowsControlService",
    "parse_power_plans",
]
