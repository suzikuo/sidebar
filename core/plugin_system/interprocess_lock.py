from __future__ import annotations

import errno
import os
import stat
from contextlib import contextmanager
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


_LOCK_CONTENTION_ERRNOS = frozenset(
    {
        errno.EACCES,
        errno.EAGAIN,
        errno.EBUSY,
        getattr(errno, "EDEADLK", errno.EBUSY),
    }
)
_LOCK_WINERRORS = frozenset({5, 32, 33})


class InterprocessLockError(RuntimeError):
    """A stable failure while acquiring or releasing a filesystem lock."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class InterprocessFileLock:
    """A non-blocking one-byte lock backed by a validated regular file."""

    def __init__(self, root, filename: str):
        try:
            raw_root = Path(root).expanduser()
            raw_stat = raw_root.lstat()
            if not stat.S_ISDIR(raw_stat.st_mode) or _is_link_or_reparse(raw_root):
                raise InterprocessLockError(
                    "UNSAFE_LOCK",
                    "Lock root must be a regular directory.",
                )
            candidate_root = raw_root.resolve(strict=True)
        except InterprocessLockError:
            raise
        except (OSError, RuntimeError, TypeError) as error:
            raise InterprocessLockError(
                "LOCK_IO_ERROR",
                f"Cannot resolve lock root: {error}",
            ) from error
        if (
            not isinstance(filename, str)
            or not filename
            or Path(filename).name != filename
        ):
            raise InterprocessLockError("UNSAFE_LOCK", "Lock filename is invalid.")
        self.root = candidate_root
        self.path = candidate_root / filename

    @contextmanager
    def acquire(self):
        handle = self._acquire()
        try:
            yield self
        except BaseException as operation_error:
            try:
                self._release(handle)
            except InterprocessLockError as release_error:
                operation_error.add_note(
                    f"Interprocess lock release also failed: {release_error}"
                )
            raise
        else:
            self._release(handle)

    def _acquire(self) -> int:
        self._validate_path()
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            handle = os.open(self.path, flags, 0o600)
        except OSError as error:
            raise _io_error(error) from error

        try:
            self._validate_open_handle(handle)
            if os.fstat(handle).st_size == 0:
                os.lseek(handle, 0, os.SEEK_SET)
                if os.write(handle, b"\0") != 1:
                    raise OSError(errno.EIO, "Cannot initialize lock file.")
                os.fsync(handle)
            os.lseek(handle, 0, os.SEEK_SET)
        except InterprocessLockError:
            _close_quietly(handle)
            raise
        except OSError as error:
            _close_quietly(handle)
            raise _io_error(error) from error

        try:
            if os.name == "nt":
                msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            _close_quietly(handle)
            if _is_contention(error):
                raise InterprocessLockError(
                    "LOCK_BUSY",
                    "Another process holds the filesystem lock.",
                ) from error
            raise _io_error(error) from error
        return handle

    def _release(self, handle: int):
        release_error = None
        try:
            if os.name == "nt":
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
        except OSError as error:
            release_error = error
        try:
            os.close(handle)
        except OSError as error:
            if release_error is None:
                release_error = error
        if release_error is not None:
            raise _io_error(release_error) from release_error

    def _validate_path(self):
        try:
            parent = self.path.parent.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise InterprocessLockError(
                "LOCK_IO_ERROR",
                f"Cannot resolve lock parent: {error}",
            ) from error
        if parent != self.root:
            raise InterprocessLockError(
                "UNSAFE_LOCK",
                "Lock file must stay directly under its root.",
            )
        try:
            path_stat = self.path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise _io_error(error) from error
        if _unsafe_file_stat(path_stat):
            raise InterprocessLockError(
                "UNSAFE_LOCK",
                "Lock must be a regular non-reparse independent file.",
            )

    def _validate_open_handle(self, handle: int):
        self._validate_path()
        try:
            path_stat = self.path.lstat()
            handle_stat = os.fstat(handle)
        except OSError as error:
            raise _io_error(error) from error
        if _unsafe_file_stat(path_stat) or not stat.S_ISREG(handle_stat.st_mode):
            raise InterprocessLockError(
                "UNSAFE_LOCK",
                "Lock must be a regular non-reparse independent file.",
            )
        if (path_stat.st_dev, path_stat.st_ino) != (
            handle_stat.st_dev,
            handle_stat.st_ino,
        ):
            raise InterprocessLockError(
                "UNSAFE_LOCK",
                "Lock file changed while being opened.",
            )


def _unsafe_file_stat(path_stat) -> bool:
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return (
        not stat.S_ISREG(path_stat.st_mode)
        or stat.S_ISLNK(path_stat.st_mode)
        or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        or getattr(path_stat, "st_nlink", 1) > 1
    )


def _is_link_or_reparse(path: Path) -> bool:
    try:
        path_stat = path.lstat()
    except OSError:
        return True
    attributes = getattr(path_stat, "st_file_attributes", 0)
    return stat.S_ISLNK(path_stat.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _is_contention(error: OSError) -> bool:
    return (
        error.errno in _LOCK_CONTENTION_ERRNOS
        or getattr(error, "winerror", None) in _LOCK_WINERRORS
    )


def _io_error(error: OSError) -> InterprocessLockError:
    return InterprocessLockError("LOCK_IO_ERROR", f"Filesystem lock failed: {error}")


def _close_quietly(handle: int):
    try:
        os.close(handle)
    except OSError:
        pass


__all__ = ["InterprocessFileLock", "InterprocessLockError"]
