import base64
import csv
import hashlib
import io
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import core.plugin_system.plugin_wheel as plugin_wheel_module
from core.plugin_system.plugin_wheel import (
    PluginWheelError,
    WheelArtifact,
    WheelInstallEntry,
    WheelLimits,
    inspect_wheel,
)
from core.plugin_system.plugin_wheel_types import (
    PluginWheelError as TypesPluginWheelError,
)
from core.plugin_system.plugin_wheel_types import WheelArtifact as TypesWheelArtifact
from core.plugin_system.plugin_wheel_types import (
    WheelInstallEntry as TypesWheelInstallEntry,
)
from core.plugin_system.plugin_wheel_types import WheelLimits as TypesWheelLimits
from tests.pe_test_utils import build_test_pe
from tests.pe_test_utils import MACHINE_ARM64


def _record_digest(content: bytes) -> str:
    encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest())
    return f"sha256={encoded.rstrip(b'=').decode('ascii')}"


class WheelBuilder:
    def __init__(
        self,
        root: Path,
        *,
        tag="py3-none-any",
        root_is_purelib=True,
        metadata_name="demo-package",
        metadata_version="2.1.0",
        requires_python=">=3.9",
    ):
        self.root = root
        self.tag = tag
        self.root_is_purelib = root_is_purelib
        self.metadata_name = metadata_name
        self.metadata_version = metadata_version
        self.requires_python = requires_python
        self.files = {"demo/__init__.py": b"VALUE = 1\n"}
        self.special_members = []
        self.record_hash_overrides = {}

    def write(self) -> Path:
        wheel_path = self.root / f"demo_package-2.1.0-{self.tag}.whl"
        dist_info = "demo_package-2.1.0.dist-info"
        metadata_lines = [
            "Metadata-Version: 2.1",
            f"Name: {self.metadata_name}",
            f"Version: {self.metadata_version}",
        ]
        if self.requires_python is not None:
            metadata_lines.append(f"Requires-Python: {self.requires_python}")
        metadata_lines.append("Requires-Dist: idna>=3")
        self.files[f"{dist_info}/METADATA"] = (
            "\n".join(metadata_lines) + "\n"
        ).encode("utf-8")
        self.files[f"{dist_info}/WHEEL"] = (
            "Wheel-Version: 1.0\n"
            "Generator: Agile Tiles tests\n"
            f"Root-Is-Purelib: {str(self.root_is_purelib).lower()}\n"
            f"Tag: {self.tag}\n"
        ).encode("utf-8")

        all_contents = dict(self.files)
        for info, content in self.special_members:
            all_contents[info.filename] = content
        record_path = f"{dist_info}/RECORD"
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\n")
        for member_path, content in sorted(all_contents.items()):
            writer.writerow(
                [
                    member_path,
                    self.record_hash_overrides.get(
                        member_path,
                        _record_digest(content),
                    ),
                    len(content),
                ]
            )
        writer.writerow([record_path, "", ""])
        self.files[record_path] = output.getvalue().encode("utf-8")

        with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for member_path, content in self.files.items():
                archive.writestr(member_path, content)
            for info, content in self.special_members:
                archive.writestr(info, content)
        return wheel_path


class PluginWheelInspectorTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def assert_wheel_error(self, code, callback):
        with self.assertRaises(PluginWheelError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)

    def inspect(self, path, **overrides):
        values = {
            "target_python_abi": "cp311",
            "target_platform": "win_amd64",
            "expected_name": "demo-package",
            "expected_version": "2.1.0",
        }
        values.update(overrides)
        return inspect_wheel(path, **values)

    def test_valid_universal_wheel_is_fully_verified(self):
        wheel = WheelBuilder(self.root).write()
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()

        artifact = self.inspect(wheel, expected_sha256=digest)

        self.assertEqual(artifact.distribution, "demo-package")
        self.assertEqual(str(artifact.version), "2.1.0")
        self.assertTrue(artifact.root_is_purelib)
        self.assertEqual(artifact.requires_python, ">=3.9")
        self.assertEqual(artifact.requirements, ("idna>=3",))
        self.assertEqual(artifact.native_extensions, ())
        self.assertEqual(artifact.target_python_abi, "cp311")
        self.assertEqual(artifact.target_platform, "win_amd64")
        self.assertTrue(
            all(isinstance(item, WheelInstallEntry) for item in artifact.install_entries)
        )
        init_entry = next(
            item
            for item in artifact.install_entries
            if item.install_path == "demo/__init__.py"
        )
        self.assertEqual(init_entry.archive_path, "demo/__init__.py")
        self.assertEqual(init_entry.size, len(b"VALUE = 1\n"))
        self.assertEqual(
            init_entry.sha256,
            hashlib.sha256(b"VALUE = 1\n").hexdigest(),
        )

    def test_facade_reexports_shared_public_types(self):
        self.assertIs(PluginWheelError, TypesPluginWheelError)
        self.assertIs(WheelArtifact, TypesWheelArtifact)
        self.assertIs(WheelInstallEntry, TypesWheelInstallEntry)
        self.assertIs(WheelLimits, TypesWheelLimits)

    def test_content_digest_is_rechecked_after_archive_inspection(self):
        wheel = WheelBuilder(self.root).write()
        real_hash_wheel = plugin_wheel_module.hash_wheel
        call_count = 0

        def changed_second_digest(handle, expected_stat):
            nonlocal call_count
            call_count += 1
            digest, final_stat = real_hash_wheel(handle, expected_stat)
            if call_count == 2:
                digest = "0" * 64 if digest != "0" * 64 else "1" * 64
            return digest, final_stat

        with patch.object(
            plugin_wheel_module,
            "hash_wheel",
            side_effect=changed_second_digest,
        ):
            self.assert_wheel_error(
                "WHEEL_FILE_CHANGED",
                lambda: self.inspect(wheel),
            )
        self.assertEqual(call_count, 2)

    def test_hashes_and_archive_inspection_share_one_file_handle(self):
        wheel = WheelBuilder(self.root).write()
        real_hash_wheel = plugin_wheel_module.hash_wheel
        real_inspect_archive = plugin_wheel_module._inspect_archive
        handles = []

        def record_hash_handle(handle, expected_stat):
            handles.append(handle.fileno())
            return real_hash_wheel(handle, expected_stat)

        def record_archive_handle(archive, *args, **kwargs):
            handles.append(archive.fp.fileno())
            return real_inspect_archive(archive, *args, **kwargs)

        with patch.object(
            plugin_wheel_module,
            "hash_wheel",
            side_effect=record_hash_handle,
        ), patch.object(
            plugin_wheel_module,
            "_inspect_archive",
            side_effect=record_archive_handle,
        ):
            self.inspect(wheel)

        self.assertEqual(len(handles), 3)
        self.assertEqual(len(set(handles)), 1)

    def test_open_race_and_unsupported_compression_are_normalized(self):
        wheel = WheelBuilder(self.root).write()
        with patch.object(Path, "open", side_effect=PermissionError("changed")):
            self.assert_wheel_error(
                "WHEEL_FILE_CHANGED",
                lambda: self.inspect(wheel),
            )

        with patch.object(
            plugin_wheel_module,
            "_inspect_archive",
            side_effect=NotImplementedError("unsupported compression"),
        ):
            self.assert_wheel_error(
                "INVALID_WHEEL_ARCHIVE",
                lambda: self.inspect(wheel),
            )

    def test_target_tags_and_requires_python_are_enforced(self):
        incompatible_tag = WheelBuilder(
            self.root,
            tag="cp312-cp312-win_amd64",
            root_is_purelib=False,
        ).write()
        self.assert_wheel_error(
            "WHEEL_TAG_INCOMPATIBLE",
            lambda: self.inspect(incompatible_tag),
        )

        incompatible_python = WheelBuilder(
            self.root,
            requires_python=">=3.12",
        ).write()
        self.assert_wheel_error(
            "WHEEL_REQUIRES_PYTHON_MISMATCH",
            lambda: self.inspect(incompatible_python),
        )

    def test_metadata_identity_and_record_hash_are_enforced(self):
        wrong_name = WheelBuilder(self.root, metadata_name="other").write()
        self.assert_wheel_error(
            "WHEEL_METADATA_IDENTITY_MISMATCH",
            lambda: self.inspect(wrong_name),
        )

        builder = WheelBuilder(self.root)
        builder.record_hash_overrides["demo/__init__.py"] = _record_digest(b"wrong")
        wrong_record = builder.write()
        self.assert_wheel_error(
            "WHEEL_RECORD_HASH_MISMATCH",
            lambda: self.inspect(wrong_record),
        )

    def test_unsafe_paths_links_pth_and_install_schemes_are_rejected(self):
        cases = []

        def make_builder(name):
            case_root = self.root / name
            case_root.mkdir()
            return WheelBuilder(case_root)

        traversal = make_builder("traversal")
        traversal.files["../escape.py"] = b"bad"
        cases.append(("UNSAFE_WHEEL_PATH", traversal.write()))

        pth = make_builder("pth")
        pth.files["activate.pth"] = b"import os\n"
        cases.append(("WHEEL_PTH_NOT_ALLOWED", pth.write()))

        script = make_builder("script")
        script.files["demo_package-2.1.0.data/scripts/run.exe"] = b"bad"
        cases.append(("WHEEL_SCHEME_NOT_ALLOWED", script.write()))

        wrong_data = make_builder("wrong-data")
        wrong_data.files["other-2.1.0.data/purelib/extra.py"] = b"bad"
        cases.append(("WHEEL_DATA_ROOT_MISMATCH", wrong_data.write()))

        collision = make_builder("collision")
        collision.files["collision"] = b"file"
        collision.files["collision/child.py"] = b"child"
        cases.append(("WHEEL_PATH_COLLISION", collision.write()))

        install_collision = make_builder("install-collision")
        install_collision.files[
            "demo_package-2.1.0.data/purelib/demo/__init__.py"
        ] = b"other"
        cases.append(
            ("WHEEL_INSTALL_PATH_COLLISION", install_collision.write())
        )

        link = make_builder("link")
        link_info = zipfile.ZipInfo("demo/link.py")
        link_info.create_system = 3
        link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
        link.special_members.append((link_info, b"../outside.py"))
        cases.append(("WHEEL_LINK_NOT_ALLOWED", link.write()))

        for code, wheel in cases:
            with self.subTest(code=code):
                self.assert_wheel_error(code, lambda path=wheel: self.inspect(path))

    def test_cp311_and_compatible_abi3_native_extensions_are_inspected(self):
        exact = WheelBuilder(
            self.root,
            tag="cp311-cp311-win_amd64",
            root_is_purelib=False,
        )
        exact.files["demo/fast.cp311-win_amd64.pyd"] = build_test_pe()
        exact_artifact = self.inspect(exact.write())
        self.assertEqual(
            exact_artifact.native_extensions,
            ("demo/fast.cp311-win_amd64.pyd",),
        )

        abi3 = WheelBuilder(
            self.root,
            tag="cp38-abi3-win_amd64",
            root_is_purelib=False,
        )
        abi3.files["demo/fast.abi3.pyd"] = build_test_pe()
        abi3_artifact = self.inspect(abi3.write())
        self.assertEqual(abi3_artifact.native_extensions, ("demo/fast.abi3.pyd",))

        dll_wheel = WheelBuilder(
            self.root,
            tag="cp311-none-win_amd64",
            root_is_purelib=False,
        )
        dll_wheel.files["demo/libs/helper.dll"] = build_test_pe(
            export_name="not_python"
        )
        dll_artifact = self.inspect(dll_wheel.write())
        self.assertEqual(dll_artifact.dlls, ("demo/libs/helper.dll",))

    def test_invalid_native_export_and_limits_are_rejected(self):
        native = WheelBuilder(
            self.root,
            tag="cp311-cp311-win_amd64",
            root_is_purelib=False,
        )
        native.files["demo/fast.cp311-win_amd64.pyd"] = build_test_pe(
            export_name="PyInit_other"
        )
        self.assert_wheel_error(
            "NATIVE_INIT_SYMBOL_MISSING",
            lambda: self.inspect(native.write()),
        )

        fake_universal = WheelBuilder(self.root, root_is_purelib=False)
        fake_universal.files["demo/fast.pyd"] = build_test_pe()
        self.assert_wheel_error(
            "WHEEL_NATIVE_TAG_MISMATCH",
            lambda: self.inspect(fake_universal.write()),
        )

        wrong_dll = WheelBuilder(
            self.root,
            tag="cp311-none-win_amd64",
            root_is_purelib=False,
        )
        wrong_dll.files["demo/helper.dll"] = build_test_pe(
            machine=MACHINE_ARM64,
        )
        self.assert_wheel_error(
            "NATIVE_MACHINE_MISMATCH",
            lambda: self.inspect(wrong_dll.write()),
        )

        limited = WheelBuilder(self.root).write()
        self.assert_wheel_error(
            "WHEEL_ENTRY_LIMIT",
            lambda: self.inspect(limited, limits=WheelLimits(max_entries=2)),
        )


if __name__ == "__main__":
    unittest.main()
