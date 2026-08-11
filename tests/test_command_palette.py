import unittest

from plugins.command_palette.models import (
    normalize_custom_command,
    normalize_provider_command,
    search_commands,
)


class CommandPaletteModelTest(unittest.TestCase):
    def test_custom_command_is_normalized_and_searchable(self):
        command = normalize_custom_command(
            {"name": "Open Logs", "target": "logs", "arguments": "--today --errors"}
        )

        self.assertEqual(command["arguments"], ["--today", "--errors"])
        self.assertTrue(command["id"].startswith("custom."))
        self.assertEqual(search_commands([command], "open error"), [command])

    def test_provider_command_requires_an_executable_route(self):
        self.assertIsNone(normalize_provider_command("sample", {"id": "x", "name": "X"}))
        command = normalize_provider_command(
            "sample",
            {
                "id": "x",
                "name": "Example",
                "route": "plugins/sample/execute",
                "payload": {"id": 1},
            },
        )
        self.assertEqual(command["id"], "sample:x")
        self.assertEqual(command["payload"], {"id": 1})


if __name__ == "__main__":
    unittest.main()
