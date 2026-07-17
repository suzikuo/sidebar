from __future__ import annotations

import keyword
import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Iterable

from build_support._inventory_common import inventory_error


_IMPORT_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_IGNORED_ROOT_SUFFIXES = (".dist-info", ".egg-info", ".data")


def extract_top_level_imports(
    distribution: Any,
    *,
    distribution_name: str,
    additive_override: Iterable[str] = (),
) -> tuple[str, ...]:
    candidates: dict[str, str] = {}
    text = _read_top_level_text(distribution, distribution_name)
    if text:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            _add_candidate(
                candidates,
                _first_segment(line),
                distribution_name=distribution_name,
            )

    try:
        files = distribution.files
    except Exception as error:
        raise inventory_error(
            "INVALID_DISTRIBUTION_FILES",
            f"Cannot read file metadata for {distribution_name}: {error}",
            distribution=distribution_name,
        ) from error
    if files is not None:
        try:
            file_entries = tuple(files)
        except Exception as error:
            raise inventory_error(
                "INVALID_DISTRIBUTION_FILES",
                f"Cannot enumerate file metadata for {distribution_name}: {error}",
                distribution=distribution_name,
            ) from error
        for entry in file_entries:
            candidate = _candidate_from_file(entry, distribution_name)
            _add_candidate(
                candidates,
                candidate,
                distribution_name=distribution_name,
            )

    try:
        overrides = tuple(additive_override)
    except (TypeError, ValueError) as error:
        raise inventory_error(
            "INVALID_TOP_LEVEL_OVERRIDE",
            f"Top-level import override for {distribution_name} is invalid.",
            distribution=distribution_name,
        ) from error
    for value in overrides:
        if not _valid_import_name(value):
            raise inventory_error(
                "INVALID_TOP_LEVEL_OVERRIDE",
                f"Top-level import override for {distribution_name} is invalid.",
                distribution=distribution_name,
            )
        _add_candidate(
            candidates,
            value,
            distribution_name=distribution_name,
        )

    return tuple(sorted(candidates.values(), key=_casefold_sort_key))


def _read_top_level_text(distribution: Any, name: str) -> str | None:
    reader = getattr(distribution, "read_text", None)
    if reader is None:
        return None
    try:
        value = reader("top_level.txt")
    except Exception as error:
        raise inventory_error(
            "INVALID_DISTRIBUTION_FILES",
            f"Cannot read top_level.txt for {name}: {error}",
            distribution=name,
        ) from error
    if value is not None and not isinstance(value, str):
        raise inventory_error(
            "INVALID_DISTRIBUTION_FILES",
            f"top_level.txt for {name} is not text.",
            distribution=name,
        )
    return value


def _candidate_from_file(entry: Any, distribution_name: str) -> str | None:
    raw_path = str(entry)
    normalized = raw_path.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    windows_path = PureWindowsPath(raw_path)
    if (
        not normalized
        or "\x00" in normalized
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or any(part in {"", "."} for part in posix_path.parts)
    ):
        raise inventory_error(
            "UNSAFE_DISTRIBUTION_FILE",
            f"File metadata for {distribution_name} contains an unsafe path.",
            distribution=distribution_name,
        )
    # Console-script RECORD entries commonly point outside site-packages.
    # They cannot own a top-level import and are never opened here.
    if ".." in posix_path.parts:
        return None
    root = posix_path.parts[0]
    if root.casefold().endswith(_IGNORED_ROOT_SUFFIXES):
        return None
    if len(posix_path.parts) > 1:
        return root
    suffix = posix_path.suffix.casefold()
    if suffix == ".py":
        return posix_path.stem
    if suffix == ".pyd":
        return posix_path.name.split(".", 1)[0]
    return None


def _first_segment(value: str) -> str | None:
    normalized = value.replace("\\", "/")
    return normalized.split("/", 1)[0] or None


def _add_candidate(
    values: dict[str, str],
    candidate: str | None,
    *,
    distribution_name: str,
) -> None:
    if not _valid_import_name(candidate):
        return
    key = candidate.casefold()
    previous = values.get(key)
    if previous is not None and previous != candidate:
        raise inventory_error(
            "AMBIGUOUS_TOP_LEVEL_IMPORT",
            f"{distribution_name} owns imports that differ only by case.",
            distribution=distribution_name,
        )
    values[key] = candidate


def _valid_import_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_IMPORT_PATTERN.fullmatch(value))
        and value.isidentifier()
        and not keyword.iskeyword(value)
    )


def _casefold_sort_key(value: str) -> tuple[str, str]:
    return value.casefold(), value
