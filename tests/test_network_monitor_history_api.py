import tempfile
import time
import unittest
from types import SimpleNamespace

from builtin_plugins.network_monitor.history_api import TrafficHistoryApi


class _Context:
    plugin_id = "network_monitor"

    def __init__(self, directory):
        self.directory = directory
        self.routes = {}

    def get_data_dir(self):
        return self.directory

    def register_api_route(self, action, handler, **_kwargs):
        route = f"plugins/{self.plugin_id}/{action}"
        self.routes[route] = handler
        return route


class TrafficHistoryApiTest(unittest.TestCase):
    def test_api_accepts_json_records_and_keeps_sources_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            context = _Context(directory)
            api = TrafficHistoryApi(context, f"{directory}/traffic.db")
            api.register_routes()
            timestamp = int(time.time())
            submit = context.routes["plugins/network_monitor/submit"]
            query = context.routes["plugins/network_monitor/query"]
            submit(
                {
                    "records": [
                        {
                            "timestamp": timestamp,
                            "source": "system",
                            "appKey": "__system__",
                            "appName": "系统",
                            "uploadBytes": 10,
                            "downloadBytes": 20,
                        },
                        {
                            "timestamp": timestamp,
                            "source": "v2ray",
                            "appKey": "__v2ray__",
                            "appName": "V2Ray",
                            "uploadBytes": 2,
                            "downloadBytes": 3,
                        },
                    ]
                },
                SimpleNamespace(),
            )
            result = query(
                {"range": "hour", "source": "v2ray"},
                SimpleNamespace(),
            )
            self.assertEqual(result["source"], "v2ray")
            self.assertEqual(result["totalUploadBytes"], 2)
            self.assertEqual(result["totalDownloadBytes"], 3)
            api.close()

    def test_v2ray_route_forces_v2ray_source(self):
        with tempfile.TemporaryDirectory() as directory:
            context = _Context(directory)
            api = TrafficHistoryApi(context, f"{directory}/traffic.db")
            api.register_routes()
            timestamp = int(time.time())
            submit = context.routes["plugins/network_monitor/submit-v2ray"]
            submit(
                {
                    "records": [
                        {
                            "timestamp": timestamp,
                            "source": "system",
                            "appKey": "x",
                            "appName": "x",
                            "uploadBytes": 1,
                            "downloadBytes": 1,
                        }
                    ]
                },
                SimpleNamespace(),
            )
            result = context.routes["plugins/network_monitor/query"](
                {"range": "hour", "source": "v2ray"},
                SimpleNamespace(),
            )
            self.assertEqual(result["totalUploadBytes"], 1)
            api.close()


if __name__ == "__main__":
    unittest.main()
