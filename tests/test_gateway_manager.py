import importlib.util
import socket
import unittest

from plugins.gateway_manager.gateway import (
    GatewayRuntime,
    RouteConfig,
    build_upstream_url,
    find_route,
    route_matches,
    strip_path_prefix,
)


def get_free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class RouteMatchingTest(unittest.TestCase):
    def test_prefix_strip_preserves_remainder(self):
        self.assertTrue(route_matches("/6694/api/user", "/6694"))
        self.assertEqual(strip_path_prefix("/6694/api/user", "/6694"), "/api/user")
        self.assertEqual(
            build_upstream_url(
                "http://127.0.0.1:6694",
                strip_path_prefix("/6694/api/user", "/6694"),
                "id=1",
            ),
            "http://127.0.0.1:6694/api/user?id=1",
        )

    def test_prefix_boundary_does_not_match_similar_port(self):
        self.assertFalse(route_matches("/66940/api", "/6694"))

    def test_longest_prefix_wins(self):
        routes = [
            RouteConfig(1, "/6694", "http://127.0.0.1:6694"),
            RouteConfig(2, "/6694/admin", "http://127.0.0.1:7777"),
        ]
        self.assertEqual(find_route("/6694/admin/users", routes).id, 2)

    def test_exact_prefix_maps_to_root(self):
        self.assertEqual(strip_path_prefix("/6694", "/6694"), "/")


ASYNC_TESTS_AVAILABLE = hasattr(unittest, "IsolatedAsyncioTestCase") and importlib.util.find_spec("aiohttp")
AsyncBaseCase = getattr(unittest, "IsolatedAsyncioTestCase", unittest.TestCase)


@unittest.skipUnless(ASYNC_TESTS_AVAILABLE, "async aiohttp tests require Python 3.8+ and aiohttp")
class GatewayIntegrationTest(AsyncBaseCase):
    async def asyncSetUp(self):
        from aiohttp import web

        async def echo(request):
            body = await request.read()
            headers = {"X-Upstream-Path": request.rel_url.raw_path}
            return web.Response(body=body or request.rel_url.raw_query_string.encode(), headers=headers)

        self.backend_port = get_free_port()
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", echo)
        self.backend_runner = web.AppRunner(app)
        await self.backend_runner.setup()
        self.backend_site = web.TCPSite(self.backend_runner, "127.0.0.1", self.backend_port)
        await self.backend_site.start()

        self.gateway_port = get_free_port()
        self.runtime = GatewayRuntime()
        started = self.runtime.start(
            [
                {
                    "id": 1,
                    "name": "test",
                    "listen_host": "127.0.0.1",
                    "listen_port": self.gateway_port,
                    "routes": [
                        {
                            "id": 1,
                            "path_prefix": "/svc",
                            "target_url": f"http://127.0.0.1:{self.backend_port}",
                            "service_name": "backend",
                            "preserve_host": False,
                        }
                    ],
                }
            ]
        )
        self.assertTrue(started)

    async def asyncTearDown(self):
        self.runtime.stop()
        await self.backend_runner.cleanup()

    async def test_http_proxy_get_and_query(self):
        from aiohttp import ClientSession

        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{self.gateway_port}/svc/hello?x=1") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["X-Upstream-Path"], "/hello")
                self.assertEqual(await response.text(), "x=1")

    async def test_http_proxy_post_body(self):
        from aiohttp import ClientSession

        async with ClientSession() as session:
            async with session.post(
                f"http://127.0.0.1:{self.gateway_port}/svc/upload",
                data=b"binary-body",
            ) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), b"binary-body")

    async def test_no_route_returns_404(self):
        from aiohttp import ClientSession

        async with ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{self.gateway_port}/missing") as response:
                self.assertEqual(response.status, 404)
