import io
import unittest

from core.plugin_system.native_binary import (
    NativeBinaryError,
    validate_windows_pe_machine,
    validate_windows_pyd,
)
from tests.pe_test_utils import (
    MACHINE_AMD64,
    MACHINE_ARM64,
    build_test_pe,
)


class NativeBinaryValidationTest(unittest.TestCase):
    def assert_native_error(self, code, content, **overrides):
        values = {
            "file_size": len(content),
            "module_name": "sample.fast",
            "platform_tag": "win_amd64",
        }
        values.update(overrides)
        with self.assertRaises(NativeBinaryError) as caught:
            validate_windows_pyd(io.BytesIO(content), **values)
        self.assertEqual(caught.exception.code, code)

    def test_matching_machine_and_python_init_export_pass(self):
        content = build_test_pe(machine=MACHINE_AMD64)

        self.assertIsNone(
            validate_windows_pyd(
                io.BytesIO(content),
                file_size=len(content),
                module_name="sample.fast",
                platform_tag="win_amd64",
            )
        )

    def test_machine_mismatch_is_rejected(self):
        self.assert_native_error(
            "NATIVE_MACHINE_MISMATCH",
            build_test_pe(machine=MACHINE_ARM64),
        )

    def test_generic_pe_machine_validation_does_not_require_python_export(self):
        content = build_test_pe(export_name="not_a_python_export")

        self.assertIsNone(
            validate_windows_pe_machine(
                io.BytesIO(content),
                file_size=len(content),
                platform_tag="win_amd64",
            )
        )

    def test_wrong_or_missing_python_init_export_is_rejected(self):
        self.assert_native_error(
            "NATIVE_INIT_SYMBOL_MISSING",
            build_test_pe(export_name="PyInit_other"),
        )

    def test_named_export_must_resolve_to_a_function(self):
        self.assert_native_error(
            "INVALID_PE_FILE",
            build_test_pe(export_ordinal=2),
        )
        self.assert_native_error(
            "INVALID_PE_FILE",
            build_test_pe(function_rva=0x70000000),
        )

    def test_truncated_or_non_pe_content_is_rejected(self):
        self.assert_native_error("INVALID_PE_FILE", b"not a PE image")
        content = build_test_pe()
        self.assert_native_error(
            "INVALID_PE_FILE",
            content,
            file_size=0x210,
        )


if __name__ == "__main__":
    unittest.main()
