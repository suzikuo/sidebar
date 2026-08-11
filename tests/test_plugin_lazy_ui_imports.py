import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PluginLazyUiImportsTest(unittest.TestCase):
    def test_heavy_plugin_views_are_not_imported_at_module_load(self):
        blocked_imports = {
            "plugins/app_launcher/plugin.py": {".views"},
            "plugins/bookmarks/plugin.py": {".dialogs", ".views"},
            "plugins/gateway_manager/plugin.py": {".web_view"},
            "plugins/network_monitor/plugin.py": {".floating", ".views"},
            "plugins/ssh_manager/plugin.py": {".views"},
            "plugins/thiefbook/plugin.py": {".config_widget"},
            "plugins/toolbox/plugin.py": {".views"},
        }

        for relative_path, blocked in blocked_imports.items():
            source = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_path)
            top_level_imports = {
                f"{'.' * node.level}{node.module or ''}"
                for node in tree.body
                if isinstance(node, ast.ImportFrom)
            }
            self.assertTrue(
                blocked.isdisjoint(top_level_imports),
                f"{relative_path} eagerly imports {blocked & top_level_imports}",
            )


if __name__ == "__main__":
    unittest.main()
