import asyncio
import re
from urllib.parse import urlsplit

import httpx
from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake

PREVIEW = re.compile(r"vb-([a-f0-9]{48})\.(.+)")
REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "if-none-match",
    "if-modified-since",
    "range",
    "sec-fetch-dest",
}
RESPONSE_HEADERS = {
    "content-type",
    "content-encoding",
    "content-language",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
    "location",
    "vary",
}
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


class PreviewProvider:
    def __init__(self, manager):
        self.manager = manager
        self.client = manager.client

    def match(self, hostname):
        match = PREVIEW.fullmatch(hostname)
        if not match or match[2] != self.manager.settings.preview_domain:
            return None
        return match[1]

    async def __call__(self, scope, receive, send, capability):
        pair = self.manager.previews.get(capability)
        if not pair or pair[0].destroying or not pair[1].sandbox or not pair[1].preview:
            if scope["type"] == "websocket":
                await WebSocket(scope, receive, send).close(1008)
            else:
                await PlainTextResponse("Preview unavailable", 404)(scope, receive, send)
            return
        session, run = pair
        path = scope.get("raw_path", scope["path"].encode()).decode("ascii", errors="replace")
        query = scope["query_string"].decode("ascii", errors="replace")
        target = httpx.URL(run.sandbox.url(4173)).copy_with(
            raw_path=(path + (f"?{query}" if query else "")).encode()
        )
        if scope["type"] == "websocket":
            await self.websocket(scope, receive, send, str(target), session)
        else:
            await self.http(scope, receive, send, target)

    async def http(self, scope, receive, send, target):
        headers = Headers(scope=scope)
        if scope["method"] not in METHODS:
            await PlainTextResponse("Method unavailable", 405)(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 2 * 1024 * 1024:
                await PlainTextResponse("Request too large", 413)(scope, receive, send)
                return
            if not message.get("more_body"):
                break
        try:
            request = self.client.build_request(
                scope["method"],
                target,
                content=bytes(body),
                headers=[(key, value) for key, value in headers.items() if key in REQUEST_HEADERS],
            )
            # A shared httpx client may learn application cookies. Never forward them.
            request.headers.pop("cookie", None)
            response = await self.client.send(request, stream=True)
        except httpx.HTTPError:
            await PlainTextResponse("Application server unavailable", 502)(scope, receive, send)
            return
        outgoing = {
            key: value for key, value in response.headers.items() if key.lower() in RESPONSE_HEADERS
        }
        if "location" in outgoing:
            location = outgoing["location"]
            origin = str(target.copy_with(path="/", query=None)).rstrip("/")
            if location.startswith(f"{origin}/"):
                outgoing["location"] = location[len(origin) :]
        outgoing.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": (
                    "frame-ancestors "
                    + self.manager.settings.app_origin
                    + "; object-src 'none'; worker-src 'none'"
                ),
            }
        )

        async def chunks():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()

        try:
            await StreamingResponse(chunks(), status_code=response.status_code, headers=outgoing)(
                scope, receive, send
            )
        finally:
            await response.aclose()

    async def websocket(self, scope, receive, send, target, session):
        socket = WebSocket(scope, receive, send)
        headers = Headers(scope=scope)
        scheme = urlsplit(self.manager.settings.app_origin).scheme
        preview_origin = f"{scheme}://" + headers["host"]
        if headers.get("origin") != preview_origin:
            await socket.close(1008)
            return
        try:
            async with connect(
                target.replace("http://", "ws://", 1),
                proxy=None,
                subprotocols=scope.get("subprotocols", []),
                open_timeout=5,
                origin=preview_origin,
                max_size=2 * 1024 * 1024,
            ) as upstream:
                await socket.accept(upstream.subprotocol)

                async def browser_to_app():
                    while True:
                        message = await socket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(
                            message.get("text")
                            if message.get("text") is not None
                            else message["bytes"]
                        )

                async def app_to_browser():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await socket.send_bytes(message)
                        else:
                            await socket.send_text(message)

                async with asyncio.timeout(self.manager.remaining(session) + 1):
                    tasks = (
                        asyncio.create_task(browser_to_app()),
                        asyncio.create_task(app_to_browser()),
                    )
                    try:
                        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
        except (ConnectionClosed, InvalidHandshake, TimeoutError, OSError, WebSocketDisconnect):
            pass
        try:
            await socket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass
