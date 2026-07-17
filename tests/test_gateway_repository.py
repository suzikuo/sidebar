import tempfile
import unittest
from pathlib import Path

from plugins.gateway_manager.models import GatewayDatabase


class GatewayRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.repository = GatewayDatabase(
            str(Path(self.temp_dir.name) / "gateway.db")
        )

    def test_service_gateway_and_route_crud(self):
        self.repository.save_service(
            {
                "name": "API",
                "target_url": "http://127.0.0.1:8000",
                "enabled": True,
                "remarks": "Backend",
            }
        )
        service = self.repository.list_services()[0]

        self.repository.save_gateway(
            {
                "name": "Local",
                "listen_host": "127.0.0.1",
                "listen_port": 8080,
                "enabled": True,
                "auto_start": False,
                "remarks": "",
            }
        )
        gateway = self.repository.list_gateways()[0]

        self.repository.save_route(
            {
                "gateway_id": gateway["id"],
                "service_id": service["id"],
                "path_prefix": "api/",
                "preserve_host": False,
                "enabled": True,
            }
        )
        route = self.repository.list_routes()[0]

        self.assertEqual(route["path_prefix"], "/api")
        self.assertEqual(route["service_name"], "API")
        self.assertEqual(route["gateway_name"], "Local")

        self.repository.save_service(
            {
                "name": "API v2",
                "target_url": "http://127.0.0.1:9000",
                "enabled": True,
                "remarks": "Updated",
            },
            service["id"],
        )
        self.assertEqual(
            self.repository.get_service(service["id"])["name"], "API v2"
        )

        self.assertTrue(self.repository.delete_route(route["id"]))
        self.assertTrue(self.repository.delete_gateway(gateway["id"]))
        self.assertTrue(self.repository.delete_service(service["id"]))

    def test_repository_validates_required_values_and_port(self):
        with self.assertRaises(ValueError):
            self.repository.save_service(
                {"name": "", "target_url": "http://127.0.0.1:8000"}
            )
        with self.assertRaises(ValueError):
            self.repository.save_gateway(
                {
                    "name": "Invalid",
                    "listen_host": "127.0.0.1",
                    "listen_port": 70000,
                }
            )


if __name__ == "__main__":
    unittest.main()
