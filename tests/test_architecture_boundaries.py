import ast
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_PATTERN = re.compile(
    r"^(?:"
    r"SELECT\s+.+?\s+FROM|"
    r"INSERT\s+INTO|"
    r"UPDATE\s+[A-Za-z0-9_]+\s+SET|"
    r"DELETE\s+FROM|"
    r"CREATE\s+TABLE|"
    r"ALTER\s+TABLE|"
    r"PRAGMA\s+"
    r")",
    re.IGNORECASE | re.DOTALL,
)
ROUTE_LITERAL_PATTERN = re.compile(r"['\"](?:core|plugins)/[A-Za-z0-9_.\-/]+['\"]")


def _python_files(*roots):
    for root in roots:
        yield from sorted((PROJECT_ROOT / root).rglob("*.py"))


class PersistenceBoundaryTest(unittest.TestCase):
    def test_sql_is_confined_to_repository_and_migration_layers(self):
        violations = []

        for path in _python_files("core", "plugins"):
            relative = path.relative_to(PROJECT_ROOT)
            if "data_layer" in relative.parts or path.name == "models.py":
                continue

            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if SQL_PATTERN.match(node.value.strip()):
                        violations.append(f"{relative}:{node.lineno}")

        self.assertEqual(
            violations,
            [],
            "SQL must be implemented by models/repositories/migrations, not UI or services.",
        )


class ApiBoundaryTest(unittest.TestCase):
    def test_frontend_route_literals_are_confined_to_typed_clients_and_adapters(self):
        source_root = PROJECT_ROOT / "front" / "src"
        violations = []

        for path in sorted(source_root.rglob("*")):
            if path.suffix not in {".ts", ".vue"}:
                continue
            if path.name.endswith("Api.ts") or path.name in {
                "webPreviewAdapter.ts",
            }:
                continue

            text = path.read_text(encoding="utf-8-sig")
            for match in ROUTE_LITERAL_PATTERN.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{line}")

        self.assertEqual(
            violations,
            [],
            "Business UI must call typed API clients instead of concrete routes.",
        )

    def test_plugins_do_not_import_other_plugin_implementations(self):
        violations = []
        plugins_root = PROJECT_ROOT / "plugins"

        for path in sorted(plugins_root.rglob("*.py")):
            relative = path.relative_to(plugins_root)
            if len(relative.parts) < 2:
                continue
            owner = relative.parts[0]
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))

            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    modules.append(node.module)
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)

                for module in modules:
                    parts = module.split(".")
                    if len(parts) >= 2 and parts[0] == "plugins" and parts[1] != owner:
                        violations.append(
                            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} -> {module}"
                        )

        self.assertEqual(
            violations,
            [],
            "Plugins must collaborate through exported APIs, not direct imports.",
        )

    def test_plugin_business_code_does_not_hardcode_api_routes(self):
        violations = []
        for path in _python_files("plugins"):
            text = path.read_text(encoding="utf-8-sig")
            for match in ROUTE_LITERAL_PATTERN.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(PROJECT_ROOT)}:{line}")

        self.assertEqual(
            violations,
            [],
            "Plugin business code must use PluginContext.call_plugin().",
        )


if __name__ == "__main__":
    unittest.main()
