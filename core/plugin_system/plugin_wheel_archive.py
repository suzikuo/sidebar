from __future__ import annotations

import base64
import csv
import hashlib
import io
import os
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from core.plugin_system.plugin_wheel_types import PluginWheelError, WheelLimits


_WINDOWS_DRIVE_PATTERN = re.compile(r"^[a-zA-Z]:")
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


def resolve_wheel_path(wheel_path, limits: WheelLimits):
    try:
        candidate = Path(wheel_path).expanduser()
        candidate_stat = os.lstat(candidate)
    except (OSError, TypeError) as error:
        raise PluginWheelError(
            "WHEEL_NOT_FOUND",
            f"Wheel file is unavailable: {error}",
        ) from error
    attributes = getattr(candidate_stat, "st_file_attributes", 0)
    if (
        not stat.S_ISREG(candidate_stat.st_mode)
        or stat.S_ISLNK(candidate_stat.st_mode)
        or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        or getattr(candidate_stat, "st_nlink", 1) > 1
    ):
        raise PluginWheelError(
            "UNSAFE_WHEEL_FILE",
            "Wheel must be a regular independent file.",
        )
    if candidate_stat.st_size > limits.max_archive_size:
        raise PluginWheelError(
            "WHEEL_ARCHIVE_SIZE_LIMIT",
            "Wheel archive exceeds the size limit.",
        )
    try:
        return candidate.resolve(strict=True), candidate_stat
    except (OSError, RuntimeError) as error:
        raise PluginWheelError(
            "WHEEL_NOT_FOUND",
            f"Cannot resolve wheel file: {error}",
        ) from error


def hash_wheel(handle, expected_stat) -> tuple[str, os.stat_result]:
    digest = hashlib.sha256()
    try:
        handle.seek(0)
        opened_stat = os.fstat(handle.fileno())
        if not same_file_snapshot(expected_stat, opened_stat):
            raise PluginWheelError(
                "WHEEL_FILE_CHANGED",
                "Wheel changed while being opened.",
            )
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        final_stat = os.fstat(handle.fileno())
        if not same_file_snapshot(opened_stat, final_stat):
            raise PluginWheelError(
                "WHEEL_FILE_CHANGED",
                "Wheel changed while being hashed.",
            )
        handle.seek(0)
    except PluginWheelError:
        raise
    except (OSError, ValueError) as error:
        raise PluginWheelError(
            "WHEEL_NOT_FOUND",
            f"Cannot hash wheel file: {error}",
        ) from error
    return digest.hexdigest(), final_stat


def validate_member(info: zipfile.ZipInfo) -> tuple[str, bool]:
    if info.flag_bits & 0x1:
        raise PluginWheelError(
            "ENCRYPTED_WHEEL_MEMBER",
            f"Encrypted wheel member is not allowed: {info.filename}",
        )
    normalized = normalize_path(info.filename)
    unix_mode = info.external_attr >> 16
    file_type = stat.S_IFMT(unix_mode)
    if file_type == stat.S_IFLNK:
        raise PluginWheelError(
            "WHEEL_LINK_NOT_ALLOWED",
            f"Wheel links are not allowed: {normalized}",
        )
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise PluginWheelError(
            "WHEEL_SPECIAL_FILE_NOT_ALLOWED",
            f"Wheel special file is not allowed: {normalized}",
        )
    windows_attributes = info.external_attr & 0xFFFF
    if windows_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
        raise PluginWheelError(
            "WHEEL_LINK_NOT_ALLOWED",
            f"Wheel reparse point is not allowed: {normalized}",
        )
    is_directory = info.is_dir() or file_type == stat.S_IFDIR
    if is_directory and info.file_size:
        raise PluginWheelError(
            "INVALID_WHEEL_MEMBER",
            f"Wheel directory has content: {normalized}",
        )
    return normalized, is_directory


def normalize_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PluginWheelError("UNSAFE_WHEEL_PATH", "Wheel member path is invalid.")
    if "\\" in value:
        raise PluginWheelError(
            "UNSAFE_WHEEL_PATH",
            f"Wheel member must use forward slashes: {value}",
        )
    normalized = value[:-1] if value.endswith("/") else value
    windows_path = PureWindowsPath(normalized)
    posix_path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or _WINDOWS_DRIVE_PATTERN.match(normalized)
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or posix_path.is_absolute()
        or any(part in {"", ".", ".."} for part in posix_path.parts)
    ):
        raise PluginWheelError(
            "UNSAFE_WHEEL_PATH",
            f"Wheel member path is unsafe: {value}",
        )
    for component in posix_path.parts:
        if any(
            character in _WINDOWS_INVALID_CHARS or ord(character) < 32
            for character in component
        ) or component.endswith((" ", ".")):
            raise PluginWheelError(
                "UNSAFE_WHEEL_PATH",
                f"Wheel member path is invalid on Windows: {value}",
            )
        if component.split(".", 1)[0].upper() in _WINDOWS_DEVICE_NAMES:
            raise PluginWheelError(
                "UNSAFE_WHEEL_PATH",
                f"Wheel member uses a Windows device name: {value}",
            )
    return "/".join(posix_path.parts)


def validate_path_collisions(path_records):
    for normalized, _ in path_records.values():
        parts = normalized.split("/")
        for index in range(1, len(parts)):
            parent_key = "/".join(parts[:index]).casefold()
            parent = path_records.get(parent_key)
            if parent is not None and not parent[1]:
                raise PluginWheelError(
                    "WHEEL_PATH_COLLISION",
                    f"Wheel file is also used as a directory: {parent[0]}",
                )


def read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    max_size: int,
) -> bytes:
    if info.file_size > max_size:
        raise PluginWheelError(
            "WHEEL_METADATA_SIZE_LIMIT",
            f"Wheel metadata exceeds the size limit: {info.filename}",
        )
    try:
        with archive.open(info, "r") as source:
            payload = source.read(max_size + 1)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginWheelError(
            "WHEEL_MEMBER_READ_FAILED",
            f"Cannot read wheel member {info.filename}: {error}",
        ) from error
    if len(payload) != info.file_size:
        raise PluginWheelError(
            "INVALID_WHEEL_MEMBER",
            f"Wheel member size changed while reading: {info.filename}",
        )
    return payload


def validate_record(
    archive: zipfile.ZipFile,
    files: dict[str, zipfile.ZipInfo],
    record_path: str,
    payload: bytes,
) -> dict[str, tuple[int, str]]:
    try:
        text = payload.decode("utf-8")
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except (UnicodeDecodeError, csv.Error) as error:
        raise PluginWheelError(
            "INVALID_WHEEL_RECORD",
            f"Cannot parse wheel RECORD: {error}",
        ) from error
    records = {}
    seen = set()
    for row in rows:
        if len(row) != 3:
            raise PluginWheelError(
                "INVALID_WHEEL_RECORD",
                "Wheel RECORD rows must contain path, hash and size.",
            )
        record_name = normalize_path(row[0])
        key = record_name.casefold()
        if key in seen:
            raise PluginWheelError(
                "DUPLICATE_WHEEL_RECORD",
                f"Wheel RECORD contains a duplicate path: {record_name}",
            )
        seen.add(key)
        records[record_name] = (row[1], row[2])

    if set(records) != set(files):
        missing = sorted(set(files) - set(records))
        extra = sorted(set(records) - set(files))
        detail = missing[0] if missing else extra[0]
        raise PluginWheelError(
            "WHEEL_RECORD_FILE_SET_MISMATCH",
            f"Wheel RECORD file set does not match the archive: {detail}",
        )

    verified = {}
    for member_path, info in files.items():
        hash_value, size_value = records[member_path]
        if member_path == record_path:
            if hash_value or size_value:
                raise PluginWheelError(
                    "INVALID_WHEEL_RECORD",
                    "Wheel RECORD must leave its own hash and size empty.",
                )
            verified[member_path] = (
                info.file_size,
                hashlib.sha256(payload).hexdigest(),
            )
            continue
        try:
            recorded_size = int(size_value)
        except ValueError as error:
            raise PluginWheelError(
                "INVALID_WHEEL_RECORD",
                f"Wheel RECORD size is invalid: {member_path}",
            ) from error
        if recorded_size != info.file_size:
            raise PluginWheelError(
                "WHEEL_RECORD_SIZE_MISMATCH",
                f"Wheel RECORD size does not match: {member_path}",
            )
        algorithm, separator, encoded_digest = hash_value.partition("=")
        if separator != "=" or algorithm.lower() != "sha256" or not encoded_digest:
            raise PluginWheelError(
                "WHEEL_RECORD_HASH_UNSUPPORTED",
                f"Wheel RECORD must use SHA-256: {member_path}",
            )
        expected_digest = _decode_record_digest(encoded_digest, member_path)
        actual_digest = hash_member(archive, info)
        if actual_digest != expected_digest:
            raise PluginWheelError(
                "WHEEL_RECORD_HASH_MISMATCH",
                f"Wheel RECORD hash does not match: {member_path}",
            )
        verified[member_path] = (recorded_size, expected_digest.hex())
    return verified


def _decode_record_digest(value: str, member_path: str) -> bytes:
    try:
        padding = "=" * (-len(value) % 4)
        digest = base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as error:
        raise PluginWheelError(
            "INVALID_WHEEL_RECORD",
            f"Wheel RECORD hash is invalid: {member_path}",
        ) from error
    if len(digest) != hashlib.sha256().digest_size:
        raise PluginWheelError(
            "INVALID_WHEEL_RECORD",
            f"Wheel RECORD SHA-256 length is invalid: {member_path}",
        )
    return digest


def hash_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        with archive.open(info, "r") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                bytes_read += len(chunk)
                if bytes_read > info.file_size:
                    raise PluginWheelError(
                        "INVALID_WHEEL_MEMBER",
                        f"Wheel member exceeds its declared size: {info.filename}",
                    )
                digest.update(chunk)
    except PluginWheelError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise PluginWheelError(
            "WHEEL_MEMBER_READ_FAILED",
            f"Cannot hash wheel member {info.filename}: {error}",
        ) from error
    if bytes_read != info.file_size:
        raise PluginWheelError(
            "INVALID_WHEEL_MEMBER",
            f"Wheel member size changed while hashing: {info.filename}",
        )
    return digest.digest()


def same_file(first, second) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def same_file_snapshot(first, second) -> bool:
    return (
        same_file(first, second)
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and getattr(first, "st_ctime_ns", None)
        == getattr(second, "st_ctime_ns", None)
    )
