import struct


MACHINE_I386 = 0x014C
MACHINE_AMD64 = 0x8664
MACHINE_ARM64 = 0xAA64


def build_test_pe(
    export_name: str = "PyInit_fast",
    *,
    machine: int = MACHINE_AMD64,
    export_ordinal: int = 0,
    function_rva: int | None = None,
) -> bytes:
    """Build a minimal PE image containing one named export for static tests."""

    pe_offset = 0x80
    optional_header_size = 0xF0
    section_table_offset = pe_offset + 24 + optional_header_size
    raw_offset = 0x200
    section_rva = 0x1000
    image = bytearray(0x400)

    image[:2] = b"MZ"
    struct.pack_into("<I", image, 0x3C, pe_offset)
    image[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into(
        "<HHIIIHH",
        image,
        pe_offset + 4,
        machine,
        1,
        0,
        0,
        0,
        optional_header_size,
        0x2022,
    )

    optional_offset = pe_offset + 24
    struct.pack_into("<H", image, optional_offset, 0x20B)
    struct.pack_into("<I", image, optional_offset + 60, raw_offset)
    struct.pack_into("<I", image, optional_offset + 108, 16)
    struct.pack_into("<II", image, optional_offset + 112, section_rva, 0x100)

    image[section_table_offset : section_table_offset + 8] = b".rdata\0\0"
    struct.pack_into(
        "<IIIIIIHHI",
        image,
        section_table_offset + 8,
        0x200,
        section_rva,
        0x200,
        raw_offset,
        0,
        0,
        0,
        0,
        0x40000040,
    )

    struct.pack_into(
        "<IIHHIIIIIII",
        image,
        raw_offset,
        0,
        0,
        0,
        0,
        section_rva + 0x80,
        1,
        1,
        1,
        section_rva + 0x28,
        section_rva + 0x2C,
        section_rva + 0x30,
    )
    struct.pack_into(
        "<I",
        image,
        raw_offset + 0x28,
        function_rva if function_rva is not None else section_rva + 0x100,
    )
    struct.pack_into("<I", image, raw_offset + 0x2C, section_rva + 0x40)
    struct.pack_into("<H", image, raw_offset + 0x30, export_ordinal)
    encoded_export = export_name.encode("ascii") + b"\0"
    image[raw_offset + 0x40 : raw_offset + 0x40 + len(encoded_export)] = encoded_export
    image[raw_offset + 0x80 : raw_offset + 0x8B] = b"sample.pyd\0"
    return bytes(image)
