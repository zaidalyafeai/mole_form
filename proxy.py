from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Iterable, List, Tuple
from urllib.parse import urlparse

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket

logger = logging.getLogger(__name__)

API_BACKEND = os.environ.get("API_BACKEND", "http://127.0.0.1:8001")
STREAMLIT_BACKEND = os.environ.get("STREAMLIT_BACKEND", "http://127.0.0.1:8501")

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

WS_SKIP_HEADERS = HOP_BY_HOP | {
    "host",
    "sec-websocket-key",
    "sec-websocket-version",
    "sec-websocket-extensions",
    "sec-websocket-protocol",
    "sec-websocket-accept",
}

WS_FORWARD_HEADERS = {
    "cookie",
    "authorization",
    "user-agent",
    "accept-language",
}

STREAM_ERRORS = (
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.StreamError,
    httpx.WriteError,
    asyncio.CancelledError,
)


def backend_host_header(backend_url: str) -> str:
    parsed = urlparse(backend_url)
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return f"{parsed.hostname}:{port}"


def is_api_path(path: str) -> bool:
    return (
        path == "/health"
        or path == "/openapi.json"
        or path.startswith("/push-metadata")
        or path.startswith("/docs")
        or path.startswith("/redoc")
    )


def pick_backend(path: str) -> str:
    return API_BACKEND if is_api_path(path) else STREAMLIT_BACKEND


def filtered_headers(headers: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    return {
        key: value
        for key, value in headers
        if key.lower() not in HOP_BY_HOP and key.lower() != "host"
    }


def upstream_http_headers(request: Request, backend: str) -> Dict[str, str]:
    headers = filtered_headers(request.headers.items())
    lowered = {key.lower() for key in headers}

    client = request.client
    if client and "x-forwarded-for" not in lowered:
        headers["X-Forwarded-For"] = client.host

    if "x-forwarded-proto" not in lowered:
        forwarded_proto = request.headers.get("x-forwarded-proto")
        headers["X-Forwarded-Proto"] = forwarded_proto or request.url.scheme or "https"

    if "x-forwarded-host" not in lowered:
        host = request.headers.get("host")
        if host:
            headers["X-Forwarded-Host"] = host

    headers["Host"] = backend_host_header(backend)
    return headers


def websocket_upstream_headers(scope: dict) -> List[Tuple[str, str]]:
    headers: List[Tuple[str, str]] = []
    for key, value in scope.get("headers", []):
        name = key.decode().lower()
        if name in WS_SKIP_HEADERS:
            continue
        if name in WS_FORWARD_HEADERS:
            headers.append((key.decode(), value.decode()))
    return headers


def client_origin(scope: dict) -> str | None:
    for key, value in scope.get("headers", []):
        if key.decode().lower() == "origin":
            return value.decode()
    return None


@asynccontextmanager
async def lifespan(app: Starlette):
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
    )
    try:
        yield
    finally:
        await app.state.http.aclose()


async def proxy_http(request: Request) -> Response:
    client: httpx.AsyncClient = request.app.state.http
    backend = pick_backend(request.url.path)
    url = f"{backend}{request.url.path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    upstream = await client.send(
        client.build_request(
            request.method,
            url,
            headers=upstream_http_headers(request, backend),
            content=await request.body(),
        ),
        stream=True,
    )

    async def stream():
        try:
            async for chunk in upstream.aiter_raw():
                if await request.is_disconnected():
                    break
                yield chunk
        except STREAM_ERRORS:
            pass
        finally:
            await upstream.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=filtered_headers(upstream.headers.items()),
    )


async def proxy_websocket(websocket: WebSocket) -> None:
    import websockets as ws_client

    backend = STREAMLIT_BACKEND
    streamlit_ws = backend.replace("http://", "ws://").replace("https://", "wss://")
    path = websocket.url.path or "/"
    if websocket.url.query:
        path = f"{path}?{websocket.url.query}"
    target = f"{streamlit_ws}{path}"

    subprotocols = websocket.scope.get("subprotocols") or []
    upstream_headers = websocket_upstream_headers(websocket.scope)
    origin = client_origin(websocket.scope)

    try:
        upstream = await ws_client.connect(
            target,
            additional_headers=upstream_headers or None,
            origin=origin,
            subprotocols=subprotocols or None,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
            open_timeout=20,
        )
    except Exception as exc:
        logger.warning("WebSocket upstream connect failed for %s: %s", target, exc)
        await websocket.close(code=1011)
        return

    await websocket.accept(subprotocol=upstream.subprotocol)

    try:

        async def client_to_upstream() -> None:
            try:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        await upstream.close()
                        break
                    if message["type"] != "websocket.receive":
                        continue
                    text = message.get("text")
                    if text is not None:
                        await upstream.send(text)
                    else:
                        await upstream.send(message["bytes"])
            except Exception:
                pass

        async def upstream_to_client() -> None:
            try:
                async for message in upstream:
                    if isinstance(message, str):
                        await websocket.send_text(message)
                    else:
                        await websocket.send_bytes(message)
            except Exception:
                pass

        tasks = [
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, return_exceptions=True)
    except Exception as exc:
        logger.warning("WebSocket proxy relay failed for %s: %s", target, exc)
    finally:
        await upstream.close()
        try:
            await websocket.close()
        except Exception:
            pass


app = Starlette(
    lifespan=lifespan,
    routes=[
        Route(
            "/{path:path}",
            proxy_http,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
        ),
        WebSocketRoute("/{path:path}", proxy_websocket),
    ],
)
