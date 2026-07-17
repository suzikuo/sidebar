import json
import runpy
import shutil
import tempfile
import unittest
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PyInstaller.utils.hooks import copy_metadata

from core.plugin_system.host_environment import HOST_DISTRIBUTIONS


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PyInstallerReleaseSpecTest(unittest.TestCase):
    def test_spec_uses_explicit_host_metadata_without_copying_core_as_data(self):
        captured = {}
        metadata_datas = {
            name: [(f"{name}.dist-info", f"{name}.dist-info")]
            for name in HOST_DISTRIBUTIONS
        }
        tree_entries = {
            "plugins": [("plugins/sample.py", "plugins/sample.py", "DATA")],
            "ui": [("ui/widget.py", "ui/widget.py", "DATA")],
        }

        def analysis(*args, **kwargs):
            captured["datas"] = tuple(kwargs["datas"])
            captured["hiddenimports"] = tuple(kwargs["hiddenimports"])
            return SimpleNamespace(
                pure=(),
                scripts=(),
                binaries=tuple(kwargs["binaries"]),
                datas=tuple(kwargs["datas"]),
            )

        def exe(*args, **kwargs):
            captured["icon"] = kwargs["icon"]
            return object()

        with patch(
            "PyInstaller.building.datastruct.Tree",
            side_effect=lambda root, **kwargs: tree_entries[root],
        ) as collected_tree, patch(
            "PyInstaller.utils.hooks.collect_all",
            side_effect=AssertionError("collect_all duplicates Python sources"),
        ) as collected_all, patch(
            "PyInstaller.utils.hooks.collect_data_files",
            return_value=[("fluent-resource", "qfluentwidgets")],
        ) as collected_data, patch(
            "PyInstaller.utils.hooks.collect_dynamic_libs",
            return_value=[("fluent-binary", "qfluentwidgets")],
        ) as collected_binaries, patch(
            "PyInstaller.utils.hooks.collect_submodules",
            return_value=["qfluentwidgets.generated"],
        ) as collected_submodules, patch(
            "PyInstaller.utils.hooks.copy_metadata",
            side_effect=lambda name: metadata_datas[name],
        ) as copied:
            runpy.run_path(
                str(PROJECT_ROOT / "AgileTiles.spec"),
                init_globals={
                    "Analysis": analysis,
                    "PYZ": lambda *args, **kwargs: object(),
                    "EXE": exe,
                    "COLLECT": lambda *args, **kwargs: object(),
                },
            )

        self.assertEqual(
            [call.args[0] for call in copied.call_args_list],
            list(HOST_DISTRIBUTIONS),
        )
        collected_all.assert_not_called()
        collected_data.assert_called_once_with("qfluentwidgets")
        collected_binaries.assert_called_once_with("qfluentwidgets")
        collected_submodules.assert_called_once_with("qfluentwidgets")
        self.assertEqual(
            [call.args[0] for call in collected_tree.call_args_list],
            ["plugins", "ui"],
        )
        for call in collected_tree.call_args_list:
            self.assertEqual(
                call.kwargs["excludes"],
                ["__pycache__", "*.pyc", "*.pyo"],
            )
        self.assertIn(
            "core.plugin_system.plugin_base",
            captured["hiddenimports"],
        )
        self.assertIn("core.security", captured["hiddenimports"])
        self.assertIn(("plugins/sample.py", "plugins"), captured["datas"])
        self.assertIn(("ui/widget.py", "ui"), captured["datas"])
        self.assertIn(("VERSION", "."), captured["datas"])
        self.assertIn(("fluent-resource", "qfluentwidgets"), captured["datas"])
        self.assertIn(metadata_datas["PySide6"][0], captured["datas"])
        self.assertIn(
            metadata_datas["PySide6-Fluent-Widgets"][0],
            captured["datas"],
        )
        self.assertFalse(
            any(
                source == "core" or destination == "core"
                for source, destination in captured["datas"]
            )
        )
        self.assertEqual(captured["icon"], ["icon.ico"])

    def test_build_entry_delegates_to_the_reviewed_spec(self):
        namespace = runpy.run_path(str(PROJECT_ROOT / "build.py"))

        with patch("subprocess.run") as run:
            namespace["build"]()

        command = run.call_args.args[0]
        self.assertEqual(
            command[:5],
            [
                namespace["sys"].executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
            ],
        )
        self.assertEqual(Path(command[5]), PROJECT_ROOT / "AgileTiles.spec")
        self.assertEqual(run.call_args.kwargs, {"cwd": PROJECT_ROOT, "check": True})

    def test_copied_metadata_exposes_versions_required_by_template(self):
        template = json.loads(
            (PROJECT_ROOT / "templates" / "hello_plugin" / "manifest.json")
            .read_text(encoding="utf-8")
        )
        requirements = tuple(
            Requirement(value) for value in template["dependencies"]["host"]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            metadata_root = Path(temp_dir)
            for requirement in requirements:
                for source, destination in copy_metadata(requirement.name):
                    shutil.copytree(source, metadata_root / destination)

            discovered = {
                canonicalize_name(distribution.metadata["Name"]): distribution.version
                for distribution in metadata.distributions(path=[str(metadata_root)])
            }

        self.assertEqual(len(requirements), 2)
        for requirement in requirements:
            name = canonicalize_name(requirement.name)
            self.assertIn(name, discovered)
            self.assertIn(discovered[name], requirement.specifier)


if __name__ == "__main__":
    unittest.main()
