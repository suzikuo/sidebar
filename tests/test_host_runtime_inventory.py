import hashlib
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path

from build_support.host_runtime_inventory import (
    BuildInventoryError,
    build_host_runtime_inventory,
    scan_runtime_dlls,
)


class FakeDistribution:
    def __init__(
        self,
        name,
        version,
        *,
        requirements=(),
        extras=(),
        files=(),
        top_level=None,
        direct_url=None,
        duplicate_name=False,
    ):
        metadata = Message()
        metadata["Name"] = name
        if duplicate_name:
            metadata["Name"] = name
        metadata["Version"] = version
        for requirement in requirements:
            metadata["Requires-Dist"] = requirement
        for extra in extras:
            metadata["Provides-Extra"] = extra
        self.metadata = metadata
        self.files = tuple(files)
        self._texts = {}
        if top_level is not None:
            self._texts["top_level.txt"] = top_level
        if direct_url is not None:
            self._texts["direct_url.json"] = direct_url

    def read_text(self, filename):
        return self._texts.get(filename)


class FakeProvider:
    def __init__(self, *distributions):
        self.records = {}
        self.calls = []
        for distribution in distributions:
            name = distribution.metadata["Name"].lower().replace("_", "-")
            self.records.setdefault(name, []).append(distribution)

    def __call__(self, name):
        self.calls.append(name)
        return tuple(self.records.get(name, ()))


def fake_dist(name, version="1.0", **kwargs):
    kwargs.setdefault("files", (f"{name.replace('-', '_')}/__init__.py",))
    return FakeDistribution(name, version, **kwargs)


class HostPackageInventoryTest(unittest.TestCase):
    ENVIRONMENT = {"python_version": "3.11", "sys_platform": "win32"}

    def assert_code(self, code, callback):
        with self.assertRaises(BuildInventoryError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def build(self, roots, provider, **kwargs):
        return build_host_runtime_inventory(
            roots,
            distribution_provider=provider,
            marker_environment=self.ENVIRONMENT,
            **kwargs,
        )

    def test_exact_closure_handles_markers_extras_growth_and_cycle(self):
        provider = FakeProvider(
            fake_dist(
                "app",
                requirements=(
                    "base>=2",
                    "optional==1; extra == 'feature'",
                    "ignored==1; python_version < '3'",
                    "shared>=1",
                ),
                extras=("feature",),
            ),
            fake_dist("base", "2.1", requirements=("shared>=1",)),
            fake_dist("optional", requirements=("shared[late]>=1",)),
            fake_dist(
                "shared",
                requirements=("late-dep==1; extra == 'late'",),
                extras=("late",),
            ),
            fake_dist("late-dep", requirements=("app>=1",)),
            fake_dist("ignored"),
        )

        packages = self.build(("app[feature]==1.0",), provider)

        self.assertEqual(
            [item.distribution for item in packages],
            ["app", "base", "late-dep", "optional", "shared"],
        )
        self.assertNotIn("ignored", provider.calls)
        self.assertEqual(provider.calls.count("shared"), 1)

    def test_missing_distribution_and_version_drift_fail_closed(self):
        missing = FakeProvider(fake_dist("app", requirements=("missing>=1",)))
        self.assert_code(
            "DISTRIBUTION_NOT_FOUND",
            lambda: self.build(("app==1",), missing),
        )

        drift = FakeProvider(
            fake_dist("app", requirements=("dependency>=2",)),
            fake_dist("dependency", "1.9"),
        )
        self.assert_code(
            "DISTRIBUTION_VERSION_MISMATCH",
            lambda: self.build(("app==1",), drift),
        )
        root_drift = FakeProvider(fake_dist("app", "2.0"))
        self.assert_code(
            "DISTRIBUTION_VERSION_MISMATCH",
            lambda: self.build(("app==1",), root_drift),
        )

    def test_roots_must_be_exact_pins_and_direct_urls_are_rejected(self):
        provider = FakeProvider(fake_dist("app"))
        for requirement in ("app", "app>=1", "app==1.*", "app==1,>=1"):
            with self.subTest(requirement=requirement):
                self.assert_code(
                    "ROOT_REQUIREMENT_NOT_PINNED",
                    lambda requirement=requirement: self.build(
                        (requirement,), provider
                    ),
                )
        self.assert_code(
            "DIRECT_URL_REQUIREMENT_UNSUPPORTED",
            lambda: self.build(("app @ https://example.invalid/app.whl",), provider),
        )

    def test_duplicate_metadata_unknown_extra_and_direct_install_are_rejected(self):
        duplicate = FakeProvider(fake_dist("app"), fake_dist("app"))
        self.assert_code(
            "DUPLICATE_DISTRIBUTION_METADATA",
            lambda: self.build(("app==1",), duplicate),
        )
        duplicate_field = FakeProvider(fake_dist("app", duplicate_name=True))
        self.assert_code(
            "INVALID_DISTRIBUTION_METADATA",
            lambda: self.build(("app==1",), duplicate_field),
        )
        no_extra = FakeProvider(fake_dist("app"))
        self.assert_code(
            "UNKNOWN_DISTRIBUTION_EXTRA",
            lambda: self.build(("app[missing]==1",), no_extra),
        )
        editable = FakeProvider(
            fake_dist(
                "app",
                direct_url=json.dumps(
                    {"url": "file:///source", "dir_info": {"editable": True}}
                ),
            )
        )
        self.assert_code(
            "EDITABLE_DISTRIBUTION_UNSUPPORTED",
            lambda: self.build(("app==1",), editable),
        )

    def test_transitive_direct_url_and_duplicate_requirement_are_rejected(self):
        direct = FakeProvider(
            fake_dist("app", requirements=("dep @ https://example.invalid/d.whl",))
        )
        self.assert_code(
            "DIRECT_URL_REQUIREMENT_UNSUPPORTED",
            lambda: self.build(("app==1",), direct),
        )
        duplicate = FakeProvider(
            fake_dist("app", requirements=("dep>=1", "dep>=1")),
            fake_dist("dep"),
        )
        self.assert_code(
            "DUPLICATE_REQUIREMENT_METADATA",
            lambda: self.build(("app==1",), duplicate),
        )

    def test_import_discovery_normalizes_paths_and_allows_shared_owners(self):
        one = FakeDistribution(
            "one",
            "1.0",
            top_level="Alpha/child\nBeta\\child\nShared\nclass\nbad-name\n",
            files=(
                "root_module.py",
                "native.cp311-win_amd64.pyd",
                "Package/module.py",
                "../../Scripts/one.exe",
                "one.dist-info/METADATA",
                "not_an_import.txt",
            ),
        )
        two = FakeDistribution(
            "two",
            "1.0",
            top_level="Shared\n",
            files=("two/__init__.py",),
        )

        packages = self.build(
            ("one==1", "two==1"),
            FakeProvider(one, two),
            top_level_overrides={"one": ("Manual", "Shared")},
        )

        by_name = {item.distribution: item for item in packages}
        self.assertEqual(
            by_name["one"].top_level_imports,
            (
                "Alpha",
                "Beta",
                "Manual",
                "native",
                "Package",
                "root_module",
                "Shared",
            ),
        )
        self.assertIn("Shared", by_name["two"].top_level_imports)

    def test_overrides_are_additive_canonical_and_closure_scoped(self):
        provider = FakeProvider(fake_dist("one"))
        self.assert_code(
            "INVALID_TOP_LEVEL_OVERRIDE",
            lambda: self.build(
                ("one==1",), provider, top_level_overrides={"One": ("extra",)}
            ),
        )
        self.assert_code(
            "UNKNOWN_TOP_LEVEL_OVERRIDE",
            lambda: self.build(
                ("one==1",),
                provider,
                top_level_overrides={"missing": ("extra",)},
            ),
        )


class RuntimeDllInventoryTest(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(BuildInventoryError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_same_basename_in_distinct_paths_keeps_path_and_content_identity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = root / "a" / "shared.dll"
            second = root / "b" / "shared.dll"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            (root / "ignored.txt").write_text("ignored", encoding="utf-8")

            dlls = scan_runtime_dlls(root)

        self.assertEqual([item.path for item in dlls], ["a/shared.dll", "b/shared.dll"])
        self.assertEqual([item.size for item in dlls], [5, 6])
        self.assertEqual(
            [item.sha256 for item in dlls],
            [hashlib.sha256(b"first").hexdigest(), hashlib.sha256(b"second").hexdigest()],
        )

    def test_empty_and_hardlinked_dlls_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "empty.dll").touch()
            self.assert_code("UNSAFE_RUNTIME_DLL", lambda: scan_runtime_dlls(root))

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            original = root / "original.dll"
            original.write_bytes(b"dll")
            try:
                os.link(original, root / "linked.dll")
            except OSError as error:
                self.skipTest(f"hard links are unavailable: {error}")
            self.assert_code("UNSAFE_RUNTIME_DLL", lambda: scan_runtime_dlls(root))

    def test_symlink_path_is_rejected_instead_of_followed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "target.dll"
            target.write_bytes(b"dll")
            link = root / "linked.dll"
            try:
                link.symlink_to(target)
            except OSError as error:
                self.skipTest(f"symbolic links are unavailable: {error}")
            self.assert_code("UNSAFE_BUNDLE_ENTRY", lambda: scan_runtime_dlls(root))


if __name__ == "__main__":
    unittest.main()
