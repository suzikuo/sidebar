import ctypes
import os
import time


WAIT_FOR_PID_FLAG = "--wait-for-pid"


class ProcessControlError(ValueError):
    """A stable restart protocol error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def extract_wait_for_pid(argv) -> tuple[int | None, list[str]]:
    """Remove the private wait flag from an argument vector."""

    cleaned = list(argv)
    matches = [
        index for index, value in enumerate(cleaned) if value == WAIT_FOR_PID_FLAG
    ]
    if not matches:
        return None, cleaned
    if len(matches) != 1:
        raise ProcessControlError(
            "INVALID_WAIT_PID", "The restart wait flag may only appear once."
        )

    index = matches[0]
    if index + 1 >= len(cleaned):
        raise ProcessControlError(
            "INVALID_WAIT_PID", "The restart wait flag requires a process id."
        )
    try:
        process_id = int(cleaned[index + 1])
    except (TypeError, ValueError) as error:
        raise ProcessControlError(
            "INVALID_WAIT_PID", "The restart wait process id must be an integer."
        ) from error
    if process_id <= 0:
        raise ProcessControlError(
            "INVALID_WAIT_PID", "The restart wait process id must be positive."
        )

    del cleaned[index : index + 2]
    return process_id, cleaned


def build_restart_command(
    executable: str,
    argv,
    parent_pid: int,
    *,
    frozen: bool,
) -> list[str]:
    """Build a restart command without duplicating a frozen executable path."""

    if not isinstance(parent_pid, int) or isinstance(parent_pid, bool) or parent_pid <= 0:
        raise ProcessControlError(
            "INVALID_WAIT_PID", "The restart parent process id must be positive."
        )

    _, cleaned = extract_wait_for_pid(argv)
    arguments = cleaned[1:] if frozen else cleaned
    return [
        str(executable),
        *arguments,
        WAIT_FOR_PID_FLAG,
        str(parent_pid),
    ]


def wait_for_process_exit(process_id: int, timeout_seconds: float = 60.0) -> bool:
    """Wait until a previous application process exits before startup continues."""

    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
        raise ProcessControlError(
            "INVALID_WAIT_PID", "The restart wait process id must be positive."
        )
    if timeout_seconds < 0:
        raise ProcessControlError(
            "INVALID_WAIT_TIMEOUT", "The restart wait timeout cannot be negative."
        )

    if os.name == "nt":
        return _wait_for_process_exit_windows(process_id, timeout_seconds)
    return _wait_for_process_exit_polling(process_id, timeout_seconds)


def _wait_for_process_exit_windows(process_id: int, timeout_seconds: float) -> bool:
    synchronize = 0x00100000
    wait_object_0 = 0x00000000
    wait_timeout = 0x00000102
    error_invalid_parameter = 87

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return True
        raise ProcessControlError(
            "WAIT_PROCESS_FAILED",
            f"Cannot wait for the previous process (Windows error {error}).",
        )

    try:
        timeout_ms = min(int(timeout_seconds * 1000), 0xFFFFFFFE)
        result = kernel32.WaitForSingleObject(handle, timeout_ms)
    finally:
        kernel32.CloseHandle(handle)

    if result == wait_object_0:
        return True
    if result == wait_timeout:
        return False
    raise ProcessControlError(
        "WAIT_PROCESS_FAILED",
        f"Cannot wait for the previous process (wait result {result}).",
    )


def _wait_for_process_exit_polling(process_id: int, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            os.kill(process_id, 0)
        except ProcessLookupError:
            return True
        except PermissionError as error:
            raise ProcessControlError(
                "WAIT_PROCESS_FAILED", "Cannot inspect the previous process."
            ) from error

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.05, remaining))
