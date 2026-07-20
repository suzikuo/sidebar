"""Windows-aware parsing for user supplied application arguments."""

import os
import shlex


def parse_command_line(value: str) -> list[str]:
    """Parse an argv string while preserving quoted spaces and Windows paths."""
    text = str(value or "").strip()
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
