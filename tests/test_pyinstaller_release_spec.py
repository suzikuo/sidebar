import json
import runpy
import shutil
import tempfile
import unittest
import warnings
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PyInstaller.building.datastruct import TOC
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from PyInstaller.utils.hooks import copy_metadata

from core.plugin_system.host_environment import HOST_DISTRIBUTIONS
from tools.build_support.pyinstaller_pruning import prune_qt_binaries, prune_qt_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PyInstallerReleaseSpecTest(unittest.TestCase):
    def test_spec_uses_explicit_host_metadata_without_copying_core_as_data(self):
        captured = {}
        metadata_datas = {
            name: [(f"{name}.dist-info", f"{name}.dist-info")]
            for name in HOST_DISTRIBUTIONS
        }
        tree_entries = {
            "resources": [("resources/web/index.html", "resources/web/index.html", "DATA")],
            "plugins": [
                (
                    "plugins/sample/plugin.py",
                    "plugins/sample/plugin.py",
                    "DATA",
                )
            ],
        }

        def analysis(*args, **kwargs):
            captured["datas"] = tuple(kwargs["datas"])
            captured["hiddenimports"] = tuple(kwargs["hiddenimports"])
            captured["excludes"] = tuple(kwargs["excludes"])
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
        collected_submodules.assert_not_called()
        self.assertEqual(
            [call.args[0] for call in collected_tree.call_args_list],
            ["resources", "plugins"],
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
        self.assertIn("core.web_ui.factory", captured["hiddenimports"])
        self.assertIn("core.web_ui.contracts", captured["hiddenimports"])
        self.assertIn("core.web_ui.web_plugin_host", captured["hiddenimports"])
        self.assertIn("PySide6.QtWebView", captured["hiddenimports"])
        self.assertNotIn("PySide6.QtWebSockets", captured["hiddenimports"])
        self.assertNotIn("PySide6.QtWebEngineCore", captured["hiddenimports"])
        self.assertNotIn("PySide6.QtWebEngineWidgets", captured["hiddenimports"])
        self.assertFalse(
            any(destination == "plugins" for _, destination in captured["datas"])
        )
        self.assertIn(("resources/web/index.html", "resources/web"), captured["datas"])
        self.assertIn(
            ("plugins/sample/plugin.py", "plugins/sample"),
            captured["datas"],
        )
        self.assertIn(("VERSION", "."), captured["datas"])
        self.assertIn(("fluent-resource", "qfluentwidgets"), captured["datas"])
        self.assertIn(metadata_datas["PySide6"][0], captured["datas"])
        self.assertIn(
            metadata_datas["PySide6-Fluent-Widgets"][0],
            captured["datas"],
        )
        self.assertIn("PIL.AvifImagePlugin", captured["excludes"])
        self.assertIn("qfluentwidgets.multimedia", captured["excludes"])
        self.assertFalse(
            any(
                source == "core" or destination == "core"
                for source, destination in captured["datas"]
            )
        )
        self.assertEqual(captured["icon"], ["icon.ico"])

    def test_spec_prunes_debug_webengine_assets_and_unused_qt_modules(self):
        self.assertEqual(
            prune_qt_data(
                [
                    ("PySide6/resources/qtwebengine_devtools_resources.debug.pak", "x", "DATA"),
                    ("host/qtwebengine_devtools_resources.debug.pak", "x", "DATA"),
                    ("PySide6/resources/qtwebengine_devtools_resources.pak", "x", "DATA"),
                    ("PySide6/resources/qtwebengine_resources.pak", "x", "DATA"),
                    ("PySide6/qml/QtQuick/Controls.qml", "x", "DATA"),
                    ("PySide6/qml/QtWebEngine/Delegates.qml", "x", "DATA"),
                    ("PySide6/translations/qtwebengine_locales/fr.pak", "x", "DATA"),
                    ("PySide6/translations/qtwebengine_locales/zh-CN.pak", "x", "DATA"),
                    ("PySide6/translations/qtbase_de.qm", "x", "DATA"),
                    ("PySide6/translations/qtbase_zh_CN.qm", "x", "DATA"),
                ]
            ),
            [
                ("PySide6/translations/qtbase_zh_CN.qm", "x", "DATA"),
            ],
        )
        self.assertEqual(
            prune_qt_binaries(
                [
                    ("PySide6/Qt6Graphs.dll", "x", "BINARY"),
                    ("PySide6/Qt6Quick.dll", "x", "BINARY"),
                ]
            ),
            [],
        )

        self.assertEqual(
            prune_qt_binaries(
                [
                    ("PySide6/Qt6WebEngineCore.dll", "x", "BINARY"),
                    ("PySide6/Qt6Quick.dll", "x", "BINARY"),
                    ("PySide6/Qt6Core.dll", "x", "BINARY"),
                ],
                include_webengine=False,
            ),
            [("PySide6/Qt6Core.dll", "x", "BINARY")],
        )
        self.assertEqual(
            prune_qt_data(
                [
                    ("PySide6/resources/icudtl.dat", "x", "DATA"),
                    ("PySide6/qml/QtQuick/Controls.qml", "x", "DATA"),
                    ("resources/app.json", "x", "DATA"),
                ],
                include_webengine=False,
            ),
            [("resources/app.json", "x", "DATA")],
        )

    def test_pruning_preserves_non_list_entry_container(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            binary_entries = TOC(
                [
                    ("PySide6/Qt6Graphs.dll", "x", "BINARY"),
                    ("PySide6/Qt6Quick.dll", "x", "BINARY"),
                ]
            )

        binaries = prune_qt_binaries(binary_entries)
        data_entries = (
            ("PySide6/resources/qtwebengine_resources.debug.pak", "x", "DATA"),
            ("PySide6/resources/qtwebengine_resources.pak", "x", "DATA"),
        )
        datas = prune_qt_data(data_entries)

        self.assertIsInstance(binaries, TOC)
        self.assertEqual(
            binaries,
            [],
        )
        self.assertIsInstance(datas, tuple)
        self.assertEqual(datas, ())

    def test_build_entry_delegates_to_the_reviewed_spec(self):
        namespace = runpy.run_path(str(PROJECT_ROOT / "tools" / "build_host.py"))
        self.assertNotIn("build_plugin_packages", namespace)

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
        self.assertEqual(run.call_args.kwargs["cwd"], PROJECT_ROOT)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(
            run.call_args.kwargs["env"]["AGILE_TILES_BUILD_PROFILE"],
            "full",
        )

    def test_build_entry_accepts_lite_profile(self):
        namespace = runpy.run_path(str(PROJECT_ROOT / "tools" / "build_host.py"))

        with patch("subprocess.run") as run:
            namespace["build"]("lite")

        self.assertEqual(
            run.call_args.kwargs["env"]["AGILE_TILES_BUILD_PROFILE"],
            "lite",
        )

    def test_copied_metadata_exposes_versions_required_by_template(self):
        template = json.loads(
            (
                PROJECT_ROOT
                / "examples"
                / "plugins"
                / "hello_plugin"
                / "manifest.json"
            ).read_text(encoding="utf-8")
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
