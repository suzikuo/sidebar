import unittest
from unittest.mock import patch

from plugins.toolbox.features.port_forward import backend


class PortForwardValidationTest(unittest.TestCase):
    def test_valid_rule_is_normalized(self):
        rule = backend.validate_proxy_rule(
            "127.0.0.1", "08080", "Example.COM.", "00443"
        )

        self.assertEqual(
            rule,
            {
                "listen_address": "127.0.0.1",
                "listen_port": "8080",
                "connect_address": "example.com",
                "connect_port": "443",
            },
        )

    def test_command_injection_tokens_are_rejected(self):
        invalid_values = (
            ("127.0.0.1;calc", "8080", "example.com", "80"),
            ("127.0.0.1", "8080;calc", "example.com", "80"),
            ("127.0.0.1", "8080", "example.com;calc", "80"),
            ("127.0.0.1", "8080", "example.com", "80;calc"),
        )

        for values in invalid_values:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    backend.validate_proxy_rule(*values)

    def test_ports_must_be_in_range(self):
        for port in ("0", "65536", "-1"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    backend.validate_proxy_rule("127.0.0.1", port, "localhost", "80")


class PortForwardCommandTest(unittest.TestCase):
    @patch.object(backend, "_run_elevated_netsh", return_value=True)
    def test_add_proxy_passes_only_normalized_arguments(self, run_elevated):
        result = backend.add_proxy("0.0.0.0", "8080", "Example.COM", "80")

        self.assertTrue(result)
        run_elevated.assert_called_once_with(
            [
                "interface",
                "portproxy",
                "add",
                "v4tov4",
                "listenport=8080",
                "listenaddress=0.0.0.0",
                "connectport=80",
                "connectaddress=example.com",
            ]
        )

    @patch.object(backend, "_run_elevated_netsh")
    def test_invalid_rule_never_runs_elevated_command(self, run_elevated):
        result = backend.add_proxy("0.0.0.0", "8080;calc", "localhost", "80")

        self.assertFalse(result)
        run_elevated.assert_not_called()

    @patch.object(backend, "_run_elevated_netsh", return_value=False)
    def test_elevated_command_failure_is_propagated(self, run_elevated):
        result = backend.delete_proxy("127.0.0.1", "8080")

        self.assertFalse(result)
        run_elevated.assert_called_once()


if __name__ == "__main__":
    unittest.main()
