from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import BinaryIO


_MACHINE_BY_PLATFORM = {
    "win32": 0x014C,
    "win_amd64": 0x8664,
    "win_arm64": 0xAA64,
}
_PE32_MAGIC = 0x010B
_PE32_PLUS_MAGIC = 0x020B
_MAX_PE_SECTIONS = 96
_MAX_EXPORT_FUNCTIONS = 65_536
_MAX_EXPORT_NAMES = 4096
_MAX_EXPORT_NAME_BYTES = 1024
_EXPORT_NAME_WINDOW_BYTES = 64 * 1024


class NativeBinaryError(ValueError):
    """A static native-extension validation failure with a stable code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Section:
    virtual_size: int
    virtual_address: int
    raw_size: int
    raw_offset: int


@dataclass(frozen=True)
class _PeHeader:
    expected_machine: int
    pe_offset: int
    machine: int
    section_count: int
    optional_header_size: int
    characteristics: int


def validate_windows_pe_machine(
    handle: BinaryIO,
    *,
    file_size: int,
    platform_tag: str,
) -> None:
    """Validate the PE machine and optional-header format without loading it."""

    header = _read_pe_header(handle, file_size, platform_tag)
    if not 1 <= header.section_count <= _MAX_PE_SECTIONS:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            f"Native binary has an invalid PE section count: {header.section_count}",
        )
    if header.optional_header_size == 0 or header.optional_header_size > 4096:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native binary has an invalid PE optional header size.",
        )
    optional_header = _read_exact(
        handle,
        header.pe_offset + 24,
        header.optional_header_size,
        file_size,
    )
    optional_magic = struct.unpack_from("<H", optional_header, 0)[0]
    expected_magic = (
        _PE32_MAGIC if header.expected_machine == 0x014C else _PE32_PLUS_MAGIC
    )
    if optional_magic != expected_magic:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native binary PE format does not match its machine architecture.",
        )


def validate_windows_pyd(
    handle: BinaryIO,
    *,
    file_size: int,
    module_name: str,
    platform_tag: str,
) -> None:
    """Validate a Windows extension module without loading or executing it."""

    header = _read_pe_header(handle, file_size, platform_tag)
    expected_machine = header.expected_machine
    expected_export = _python_init_export(module_name)
    pe_offset = header.pe_offset
    section_count = header.section_count
    optional_header_size = header.optional_header_size
    if not 1 <= section_count <= _MAX_PE_SECTIONS:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            f"Native module has an invalid PE section count: {section_count}",
        )
    if optional_header_size == 0 or optional_header_size > 4096:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module has an invalid PE optional header size.",
        )

    optional_offset = pe_offset + 24
    optional_header = _read_exact(
        handle,
        optional_offset,
        optional_header_size,
        file_size,
    )
    optional_magic = struct.unpack_from("<H", optional_header, 0)[0]
    if optional_magic == _PE32_MAGIC:
        directory_count_offset = 92
        data_directories_offset = 96
    elif optional_magic == _PE32_PLUS_MAGIC:
        directory_count_offset = 108
        data_directories_offset = 112
    else:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            f"Native module uses an unsupported PE optional header: 0x{optional_magic:04x}",
        )
    expected_magic = _PE32_MAGIC if expected_machine == 0x014C else _PE32_PLUS_MAGIC
    if optional_magic != expected_magic:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module PE format does not match its machine architecture.",
        )
    if optional_header_size < data_directories_offset + 8:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module PE optional header is truncated.",
        )

    size_of_headers = struct.unpack_from("<I", optional_header, 60)[0]
    directory_count = struct.unpack_from(
        "<I", optional_header, directory_count_offset
    )[0]
    if not 0 < size_of_headers <= file_size:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module has an invalid PE header size.",
        )
    if directory_count == 0:
        _raise_missing_export(expected_export)

    export_rva, export_size = struct.unpack_from(
        "<II", optional_header, data_directories_offset
    )
    if export_rva == 0 or export_size == 0:
        _raise_missing_export(expected_export)
    if export_size < 40:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module PE export directory is truncated.",
        )

    section_table_offset = optional_offset + optional_header_size
    section_table = _read_exact(
        handle,
        section_table_offset,
        section_count * 40,
        file_size,
    )
    sections = []
    for index in range(section_count):
        section_offset = index * 40
        virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
            "<IIII", section_table, section_offset + 8
        )
        if raw_size and raw_offset + raw_size > file_size:
            raise NativeBinaryError(
                "INVALID_PE_FILE",
                "Native module PE section extends beyond the file.",
            )
        sections.append(
            _Section(
                virtual_size=virtual_size,
                virtual_address=virtual_address,
                raw_size=raw_size,
                raw_offset=raw_offset,
            )
        )

    export_offset = _rva_to_offset(
        export_rva,
        40,
        size_of_headers,
        sections,
        file_size,
    )
    export_directory = _read_exact(handle, export_offset, 40, file_size)
    (
        _flags,
        _export_timestamp,
        _major_version,
        _minor_version,
        _image_name_rva,
        _ordinal_base,
        function_count,
        name_count,
        functions_rva,
        names_rva,
        ordinals_rva,
    ) = struct.unpack("<IIHHIIIIIII", export_directory)
    if name_count == 0:
        _raise_missing_export(expected_export)
    if function_count == 0 or name_count > function_count:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module has an inconsistent PE export directory.",
        )
    if function_count > _MAX_EXPORT_FUNCTIONS:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module has too many PE exports.",
        )
    if name_count > _MAX_EXPORT_NAMES:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module has too many named PE exports.",
        )

    name_table_size = name_count * 4
    name_table_offset = _rva_to_offset(
        names_rva,
        name_table_size,
        size_of_headers,
        sections,
        file_size,
    )
    name_table = _read_exact(
        handle,
        name_table_offset,
        name_table_size,
        file_size,
    )
    function_table_size = function_count * 4
    function_table_offset = _rva_to_offset(
        functions_rva,
        function_table_size,
        size_of_headers,
        sections,
        file_size,
    )
    function_table = _read_exact(
        handle,
        function_table_offset,
        function_table_size,
        file_size,
    )
    ordinal_table_size = name_count * 2
    ordinal_table_offset = _rva_to_offset(
        ordinals_rva,
        ordinal_table_size,
        size_of_headers,
        sections,
        file_size,
    )
    ordinal_table = _read_exact(
        handle,
        ordinal_table_offset,
        ordinal_table_size,
        file_size,
    )

    name_records = []
    for index, (name_rva,) in enumerate(struct.iter_unpack("<I", name_table)):
        name_records.append(
            (
                _rva_to_offset(
                    name_rva,
                    1,
                    size_of_headers,
                    sections,
                    file_size,
                ),
                index,
            )
        )
    expected_index = _find_export_name(
        handle,
        name_records,
        expected_export,
        file_size,
    )
    if expected_index is None:
        _raise_missing_export(expected_export)

    function_index = struct.unpack_from(
        "<H", ordinal_table, expected_index * 2
    )[0]
    if function_index >= function_count:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module initialization export has an invalid ordinal.",
        )
    function_rva = struct.unpack_from(
        "<I", function_table, function_index * 4
    )[0]
    if function_rva == 0:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module initialization export has no function address.",
        )
    if export_rva <= function_rva < export_rva + export_size:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module initialization export cannot be a forwarded symbol.",
        )
    _rva_to_offset(
        function_rva,
        1,
        size_of_headers,
        sections,
        file_size,
    )


def _python_init_export(module_name: str) -> bytes:
    if not isinstance(module_name, str) or not module_name:
        raise NativeBinaryError(
            "INVALID_NATIVE_MODULE",
            "Native module name must be a dotted Python import name.",
        )
    leaf_name = module_name.rsplit(".", 1)[-1]
    if not leaf_name.isidentifier():
        raise NativeBinaryError(
            "INVALID_NATIVE_MODULE",
            "Native module name must end with a Python identifier.",
        )
    try:
        encoded_name = leaf_name.encode("ascii")
        export_name = b"PyInit_" + encoded_name
    except UnicodeEncodeError:
        encoded_name = leaf_name.encode("punycode").replace(b"-", b"_")
        export_name = b"PyInitU_" + encoded_name
    if len(export_name) > _MAX_EXPORT_NAME_BYTES:
        raise NativeBinaryError(
            "INVALID_NATIVE_MODULE",
            "Native module initialization symbol is too long.",
        )
    return export_name


def _read_pe_header(
    handle: BinaryIO,
    file_size: int,
    platform_tag: str,
) -> _PeHeader:
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 64:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native binary is too small to contain a PE header.",
        )
    expected_machine = _MACHINE_BY_PLATFORM.get(str(platform_tag).lower())
    if expected_machine is None:
        raise NativeBinaryError(
            "NATIVE_PLATFORM_UNSUPPORTED",
            f"Unsupported Windows native-binary platform: {platform_tag}",
        )
    dos_header = _read_exact(handle, 0, 64, file_size)
    if dos_header[:2] != b"MZ":
        raise NativeBinaryError("INVALID_PE_FILE", "Native binary has no DOS header.")
    pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
    pe_header = _read_exact(handle, pe_offset, 24, file_size)
    if pe_header[:4] != b"PE\0\0":
        raise NativeBinaryError("INVALID_PE_FILE", "Native binary has no PE signature.")
    (
        machine,
        section_count,
        _timestamp,
        _symbol_table,
        _symbol_count,
        optional_header_size,
        characteristics,
    ) = struct.unpack_from("<HHIIIHH", pe_header, 4)
    if machine != expected_machine:
        raise NativeBinaryError(
            "NATIVE_MACHINE_MISMATCH",
            f"Native binary PE machine 0x{machine:04x} does not match "
            f"{platform_tag} (0x{expected_machine:04x}).",
        )
    return _PeHeader(
        expected_machine=expected_machine,
        pe_offset=pe_offset,
        machine=machine,
        section_count=section_count,
        optional_header_size=optional_header_size,
        characteristics=characteristics,
    )


def _rva_to_offset(
    rva: int,
    size: int,
    size_of_headers: int,
    sections: list[_Section],
    file_size: int,
) -> int:
    if rva < size_of_headers and rva + size <= size_of_headers:
        if rva + size <= file_size:
            return rva
    for section in sections:
        relative = rva - section.virtual_address
        if relative < 0:
            continue
        mapped_size = max(section.virtual_size, section.raw_size)
        if relative >= mapped_size or relative + size > section.raw_size:
            continue
        offset = section.raw_offset + relative
        if offset + size <= file_size:
            return offset
    raise NativeBinaryError(
        "INVALID_PE_FILE",
        f"Native module PE RVA 0x{rva:08x} is not backed by file data.",
    )


def _find_export_name(
    handle: BinaryIO,
    name_records: list[tuple[int, int]],
    expected_export: bytes,
    file_size: int,
) -> int | None:
    window_start = -1
    window = b""
    for offset, index in sorted(name_records):
        if not window_start <= offset < window_start + len(window):
            window_start = offset
            window = _read_exact(
                handle,
                offset,
                min(_EXPORT_NAME_WINDOW_BYTES, file_size - offset),
                file_size,
            )
        relative_offset = offset - window_start
        end_offset = min(
            len(window),
            relative_offset + _MAX_EXPORT_NAME_BYTES + 1,
        )
        raw_name = window[relative_offset:end_offset]
        if b"\0" not in raw_name and end_offset == len(window):
            available = min(_MAX_EXPORT_NAME_BYTES + 1, file_size - offset)
            raw_name = _read_exact(handle, offset, available, file_size)
        if _parse_export_name(raw_name) == expected_export:
            return index
    return None


def _parse_export_name(raw_name: bytes) -> bytes:
    terminator = raw_name.find(b"\0")
    if terminator < 0 or terminator > _MAX_EXPORT_NAME_BYTES:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module contains an invalid PE export name.",
        )
    return raw_name[:terminator]


def _read_exact(
    handle: BinaryIO,
    offset: int,
    size: int,
    file_size: int,
) -> bytes:
    if offset < 0 or size < 0 or offset > file_size or size > file_size - offset:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module PE structure extends beyond the file.",
        )
    try:
        position = handle.seek(offset)
        if position is not None and position != offset:
            raise NativeBinaryError(
                "INVALID_PE_FILE",
                "Native module stream could not seek to a PE structure.",
            )
        data = handle.read(size)
    except NativeBinaryError:
        raise
    except (EOFError, OSError, ValueError) as error:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            f"Cannot read native module PE structure: {error}",
        ) from error
    if not isinstance(data, (bytes, bytearray)) or len(data) != size:
        raise NativeBinaryError(
            "INVALID_PE_FILE",
            "Native module PE structure is truncated.",
        )
    return bytes(data)


def _raise_missing_export(expected_export: bytes) -> None:
    raise NativeBinaryError(
        "NATIVE_INIT_SYMBOL_MISSING",
        f"Native module does not export {expected_export.decode('ascii')}.",
    )
