import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

from core.logger import logger
from plugins.gateway_manager.models import normalize_path_prefix

try:
    import aiohttp
    from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector, WSMsgType, web
except ImportError:  # pragma: no cover - exercised only when dependency is missing
    aiohttp = None
    ClientError = Exception
    ClientSession = None
    ClientTimeout = None
    TCPConnector = None
    WSMsgType = None
    web = None


CHUNK_SIZE = 64 * 1024
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
WS_HANDSHAKE_HEADERS = {
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
}
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie"}


@dataclass(frozen=True)
class RouteConfig:
    id: int
    path_prefix: str
    target_url: str
    service_name: str = ""
    preserve_host: bool = False


@dataclass(frozen=True)
class GatewayConfig:
    id: int
    name: str
    listen_host: str
    listen_port: int
    routes: Tuple[RouteConfig, ...] = field(default_factory=tuple)

    @property
    def bind_key(self):
        return self.listen_host, self.listen_port


@dataclass
class GatewaySite:
    config: GatewayConfig
    runner: object = None
    site: object = None
    running: bool = False
    error: str = ""
    requests_total: int = 0
    last_request_at: float = 0


def route_matches(path: str, prefix: str) -> bool:
    prefix = normalize_path_prefix(prefix)
    if prefix == "/":
        return True
    return path == prefix or path.startswith(prefix + "/")


def strip_path_prefix(path: str, prefix: str) -> str:
    prefix = normalize_path_prefix(prefix)
    if prefix == "/":
        return path or "/"
    if path == prefix:
        return "/"
    return path[len(prefix) :] or "/"


def find_route(path: str, routes: Iterable[RouteConfig]) -> Optional[RouteConfig]:
    for route in sorted(
        routes, key=lambda item: len(normalize_path_prefix(item.path_prefix)), reverse=True
    ):
        if route_matches(path, route.path_prefix):
            return route
    return None


def build_upstream_url(target_url: str, stripped_path: str, raw_query: str = "") -> str:
    parsed = urlsplit(target_url)
    base_path = parsed.path.rstrip("/")
    if stripped_path == "/":
        upstream_path = base_path or "/"
    elif base_path:
        upstream_path = base_path + stripped_path
    else:
        upstream_path = stripped_path
    return urlunsplit((parsed.scheme, parsed.netloc, upstream_path, raw_query, ""))


def http_to_ws_url(url: str) -> str:
    parsed = urlsplit(url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, parsed.path, parsed.query, ""))


def safe_headers_for_log(headers) -> Dict[str, str]:
    result = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADERS:
            result[key] = "***"
        else:
            result[key] = value
    return result


class GatewayRuntime:
    def __init__(self):
        self._thread = None
        self._loop = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._session = None
        self._sites: Dict[int, GatewaySite] = {}
        self._lock = threading.Lock()
        self._status: Dict[int, dict] = {}
        self._logs = deque(maxlen=300)

    def start(self, config: List[dict]) -> bool:
        if aiohttp is None:
            self._record_log("error", "aiohttp is not installed; gateway runtime cannot start")
            return False

        if self._thread is None or not self._thread.is_alive():
            self._ready.clear()
            self._stopped.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="GatewayRuntimeLoop",
                daemon=True,
            )
            self._thread.start()
            if not self._ready.wait(timeout=5):
                self._record_log("error", "Gateway runtime loop did not start in time")
                return False

        return self.apply_config(config)

    def apply_config(self, config: List[dict]) -> bool:
        if not self._loop or not self._loop.is_running():
            return False
        future = asyncio.run_coroutine_threadsafe(
            self._apply_config(self._parse_config(config)), self._loop
        )
        try:
            future.result(timeout=10)
            return True
        except Exception as exc:
            self._record_log("error", f"Failed to apply gateway config: {exc}")
            logger.error("Failed to apply gateway config", exc_info=True)
            return False

    def stop_gateway(self, gateway_id: int) -> bool:
        if not self._loop or not self._loop.is_running():
            return True
        future = asyncio.run_coroutine_threadsafe(self._stop_site(int(gateway_id)), self._loop)
        try:
            future.result(timeout=10)
            return True
        except Exception as exc:
            self._record_log("error", f"Failed to stop gateway {gateway_id}: {exc}")
            logger.error("Failed to stop gateway", exc_info=True)
            return False

    def stop(self):
        if not self._loop or not self._loop.is_running():
            return

        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(timeout=10)
        except Exception as exc:
            logger.error(f"Gateway runtime shutdown failed: {exc}", exc_info=True)

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._loop = None
        self._ready.clear()
        self._stopped.set()

    def get_status(self) -> Dict[int, dict]:
        with self._lock:
            return {key: value.copy() for key, value in self._status.items()}

    def get_logs(self):
        with self._lock:
            return list(self._logs)

    def running_count(self) -> int:
        status = self.get_status()
        return sum(1 for item in status.values() if item.get("running"))

    def _run_loop(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

    def _parse_config(self, config: List[dict]) -> List[GatewayConfig]:
        parsed = []
        for gateway in config:
            routes = tuple(
                RouteConfig(
                    id=int(route["id"]),
                    path_prefix=normalize_path_prefix(route["path_prefix"]),
                    target_url=route["target_url"],
                    service_name=route.get("service_name", ""),
                    preserve_host=bool(route.get("preserve_host", False)),
                )
                for route in gateway.get("routes", [])
            )
            parsed.append(
                GatewayConfig(
                    id=int(gateway["id"]),
                    name=gateway["name"],
                    listen_host=gateway["listen_host"],
                    listen_port=int(gateway["listen_port"]),
                    routes=routes,
                )
            )
        return parsed

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=None, sock_connect=10, sock_read=None)
            connector = TCPConnector(limit=0, ttl_dns_cache=300, enable_cleanup_closed=True)
            self._session = ClientSession(
                timeout=timeout,
                connector=connector,
                auto_decompress=False,
            )

    async def _apply_config(self, desired_configs: List[GatewayConfig]):
        await self._ensure_session()
        desired = {config.id: config for config in desired_configs}

        for gateway_id in list(self._sites.keys()):
            if gateway_id not in desired:
                await self._stop_site(gateway_id)

        for config in desired_configs:
            site = self._sites.get(config.id)
            if site and site.config.bind_key == config.bind_key:
                site.config = config
                self._set_gateway_status(site)
                self._record_log("info", f"Updated routes for gateway {config.name}")
            else:
                if site:
                    await self._stop_site(config.id)
                await self._start_site(config)

    async def _start_site(self, config: GatewayConfig):
        site_state = GatewaySite(config=config)
        self._sites[config.id] = site_state

        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._make_handler(config.id))

        runner = web.AppRunner(app, access_log=None)
        site_state.runner = runner
        try:
            await runner.setup()
            site = web.TCPSite(runner, config.listen_host, config.listen_port, reuse_address=True)
            site_state.site = site
            await site.start()
            site_state.running = True
            site_state.error = ""
            self._record_log(
                "info",
                f"Gateway {config.name} listening on {config.listen_host}:{config.listen_port}",
            )
        except Exception as exc:
            site_state.running = False
            site_state.error = str(exc)
            self._record_log(
                "error",
                f"Gateway {config.name} failed to bind {config.listen_host}:{config.listen_port}: {exc}",
            )
            try:
                await runner.cleanup()
            except Exception:
                pass

        self._set_gateway_status(site_state)

    async def _stop_site(self, gateway_id: int):
        site_state = self._sites.pop(gateway_id, None)
        if not site_state:
            return
        try:
            if site_state.runner:
                await site_state.runner.cleanup()
        finally:
            site_state.running = False
            self._set_gateway_status(site_state)
            self._record_log("info", f"Gateway {site_state.config.name} stopped")

    async def _shutdown(self):
        for gateway_id in list(self._sites.keys()):
            await self._stop_site(gateway_id)
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
        with self._lock:
            self._status.clear()

    def _make_handler(self, gateway_id: int):
        async def handler(request):
            return await self._handle_request(gateway_id, request)

        return handler

    async def _handle_request(self, gateway_id: int, request):
        site_state = self._sites.get(gateway_id)
        if not site_state or not site_state.running:
            return web.Response(status=503, text="Gateway is not running")

        config = site_state.config
        site_state.requests_total += 1
        site_state.last_request_at = time.time()
        self._set_gateway_status(site_state)

        raw_path = request.rel_url.raw_path or "/"
        raw_query = request.rel_url.raw_query_string
        route = find_route(raw_path, config.routes)
        if not route:
            self._record_log("warning", f"No route for {request.method} {raw_path} on {config.name}")
            return web.Response(status=404, text="No matching gateway route")

        stripped_path = strip_path_prefix(raw_path, route.path_prefix)
        upstream_url = build_upstream_url(route.target_url, stripped_path, raw_query)

        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await self._proxy_websocket(request, route, upstream_url)

        return await self._proxy_http(request, route, upstream_url)

    async def _proxy_http(self, request, route: RouteConfig, upstream_url: str):
        await self._ensure_session()
        headers = self._forward_headers(request.headers, route, upstream_url)

        data = None
        if request.can_read_body:
            data = request.content.iter_chunked(CHUNK_SIZE)

        started = time.perf_counter()
        try:
            async with self._session.request(
                request.method,
                upstream_url,
                headers=headers,
                data=data,
                allow_redirects=False,
                skip_auto_headers={"User-Agent", "Content-Type"},
            ) as upstream:
                response = web.StreamResponse(
                    status=upstream.status,
                    reason=upstream.reason,
                )
                for key_bytes, value_bytes in upstream.raw_headers:
                    key = key_bytes.decode("latin-1")
                    if key.lower() in HOP_BY_HOP_HEADERS:
                        continue
                    response.headers.add(key, value_bytes.decode("latin-1"))

                await response.prepare(request)
                async for chunk in upstream.content.iter_chunked(CHUNK_SIZE):
                    await response.write(chunk)
                await response.write_eof()

                elapsed_ms = int((time.perf_counter() - started) * 1000)
                self._record_log(
                    "info",
                    f"{request.method} {request.rel_url} -> {upstream.status} {elapsed_ms}ms",
                )
                return response
        except (ClientError, asyncio.TimeoutError, OSError) as exc:
            self._record_log("error", f"Upstream error for {upstream_url}: {exc}")
            return web.Response(status=502, text="Bad Gateway")

    async def _proxy_websocket(self, request, route: RouteConfig, upstream_url: str):
        await self._ensure_session()
        ws_url = http_to_ws_url(upstream_url)
        protocols = self._extract_protocols(request.headers)
        headers = self._forward_headers(
            request.headers,
            route,
            upstream_url,
            exclude=WS_HANDSHAKE_HEADERS | HOP_BY_HOP_HEADERS,
        )

        try:
            upstream_ws = await self._session.ws_connect(
                ws_url,
                headers=headers,
                protocols=protocols,
                autoping=False,
                autoclose=False,
            )
        except (ClientError, asyncio.TimeoutError, OSError) as exc:
            self._record_log("error", f"WebSocket upstream error for {ws_url}: {exc}")
            return web.Response(status=502, text="Bad Gateway")

        client_ws = web.WebSocketResponse(protocols=protocols, autoping=False, autoclose=False)
        await client_ws.prepare(request)

        async def client_to_upstream():
            async for msg in client_ws:
                await self._forward_ws_message(msg, upstream_ws)

        async def upstream_to_client():
            async for msg in upstream_ws:
                await self._forward_ws_message(msg, client_ws)

        tasks = [
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await upstream_ws.close()
        await client_ws.close()
        for task in done:
            if task.exception():
                self._record_log("warning", f"WebSocket proxy ended with error: {task.exception()}")
        self._record_log("info", f"WebSocket proxied {request.rel_url}")
        return client_ws

    async def _forward_ws_message(self, msg, target):
        if msg.type == WSMsgType.TEXT:
            await target.send_str(msg.data)
        elif msg.type == WSMsgType.BINARY:
            await target.send_bytes(msg.data)
        elif msg.type == WSMsgType.PING:
            await target.ping(msg.data)
        elif msg.type == WSMsgType.PONG:
            await target.pong(msg.data)
        elif msg.type == WSMsgType.CLOSE:
            await target.close(code=msg.data or 1000)
        elif msg.type == WSMsgType.ERROR:
            raise RuntimeError(str(msg.data))

    def _forward_headers(self, request_headers, route: RouteConfig, upstream_url: str, exclude=None):
        exclude = {item.lower() for item in (exclude or HOP_BY_HOP_HEADERS)}
        headers = {}
        for key, value in request_headers.items():
            if key.lower() in exclude:
                continue
            headers[key] = value

        if not route.preserve_host:
            parsed = urlsplit(upstream_url)
            headers["Host"] = parsed.netloc
        return headers

    def _extract_protocols(self, headers) -> List[str]:
        values = headers.getall("Sec-WebSocket-Protocol", [])
        protocols = []
        for value in values:
            protocols.extend(item.strip() for item in value.split(",") if item.strip())
        return protocols

    def _set_gateway_status(self, site_state: GatewaySite):
        with self._lock:
            self._status[site_state.config.id] = {
                "id": site_state.config.id,
                "name": site_state.config.name,
                "listen_host": site_state.config.listen_host,
                "listen_port": site_state.config.listen_port,
                "running": site_state.running,
                "error": site_state.error,
                "routes": len(site_state.config.routes),
                "requests_total": site_state.requests_total,
                "last_request_at": site_state.last_request_at,
            }

    def _record_log(self, level: str, message: str):
        entry = {
            "time": time.strftime("%H:%M:%S"),
            "level": level,
            "message": message,
        }
        with self._lock:
            self._logs.appendleft(entry)
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
