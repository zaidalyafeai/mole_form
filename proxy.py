from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Iterable, Tuple

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

STREAM_ERRORS = (
    httpx.ReadError,
    httpx.RemoteProtocolError,
    httpx.StreamError,
    httpx.WriteError,
    asyncio.CancelledError,
)


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
            headers=filtered_headers(request.headers.items()),
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

    streamlit_ws = STREAMLIT_BACKEND.replace("http://", "ws://").replace("https://", "wss://")
    path = websocket.url.path or "/"
    if websocket.url.query:
        path = f"{path}?{websocket.url.query}"
    target = f"{streamlit_ws}{path}"

    extra_headers = [
        (key.decode(), value.decode())
        for key, value in websocket.scope.get("headers", [])
        if key.decode().lower() != "host"
    ]

    await websocket.accept()

    try:
        async with ws_client.connect(target, extra_headers=extra_headers) as upstream:

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
    except Exception:
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
