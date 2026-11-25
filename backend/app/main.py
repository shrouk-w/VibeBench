import asyncio
from contextlib import asynccontextmanager, suppress
from secrets import compare_digest

import httpx
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers

from app.agents.opencode import OpenCodeAgentProvider
from app.exports.archive import ZipExporter
from app.mcp.registry import MCPProvider
from app.models.catalog import ModelsDevProvider
from app.previews.proxy import PreviewProvider
from app.sandboxes.docker_provider import DockerSandboxProvider
from app.security.broker import CredentialBroker
from app.security.requests import RateLimiter, verify_turnstile
from app.sessions.manager import SessionManager
from app.sessions.types import CreateComparison, Instruction
from app.settings import Settings

BODY_LIMIT = 2 * 1024 * 1024
SIDES = {"a", "b"}


class Gateway:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        state = scope["app"].state
        headers = Headers(scope=scope)
        path = scope["path"]
        internal = path == "/internal/provider/chat/completions"
        health = path in {"/api/health/live", "/api/health/ready"}
        trusted = not state.settings.gateway_secret or compare_digest(
            headers.get("x-vb-gateway", "").encode(), state.settings.gateway_secret.encode()
        )
        if not trusted and not (health or internal):
            if scope["type"] == "websocket":
                await WebSocket(scope, receive, send).close(1008)
            else:
                await JSONResponse({"detail": "Not found"}, status_code=404)(scope, receive, send)
            return
        if trusted:
            hostname = headers.get("host", "").split(":", 1)[0]
            capability = state.preview.match(hostname)
            if capability:
                await state.preview(scope, receive, send, capability)
                return
        if scope["type"] == "http" and scope["method"] in {"POST", "PATCH", "PUT"}:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > BODY_LIMIT:
                    await JSONResponse({"detail": "Request too large"}, status_code=413)(
                        scope, receive, send
                    )
                    return
                if not message.get("more_body"):
                    break

            replay = True

            async def read_buffer():
                nonlocal replay
                if replay:
                    replay = False
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, read_buffer, send)
            return
        await self.app(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    *,
    sandbox_factory=DockerSandboxProvider,
    agent_factory=OpenCodeAgentProvider,
    catalog_factory=ModelsDevProvider,
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(trust_env=False, timeout=25, follow_redirects=False) as client:
            sandboxes = sandbox_factory(settings) if settings.sandbox_enabled else None
            if sandboxes:
                await sandboxes.cleanup_orphans()
            broker = CredentialBroker(client)
            mcp = MCPProvider()
            catalog = catalog_factory(client)
            manager = SessionManager(
                settings, client, catalog, mcp, broker, sandboxes, agent_factory(client)
            )
            app.state.manager = manager
            app.state.preview = PreviewProvider(manager)
            app.state.exporter = (
                ZipExporter(sandboxes.client, settings.export_mb) if sandboxes else None
            )
            app.state.limiter = RateLimiter()
            reaper = asyncio.create_task(manager.reap())
            try:
                yield
            finally:
                reaper.cancel()
                with suppress(asyncio.CancelledError):
                    await reaper
                await asyncio.gather(
                    *(manager.destroy(item) for item in manager.sessions.values()),
                    return_exceptions=True,
                )

    app = FastAPI(
        title="VibeBench", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(Gateway)
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    def owned(request: Request, session_id: str, *, mutate=False):
        if mutate and request.headers.get("origin") != settings.app_origin:
            raise HTTPException(403, "Unexpected browser origin")
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        return request.app.state.manager.owned(session_id, token)

    @app.get("/api/health/live")
    async def liveness():
        return {"status": "ok"}

    @app.get("/api/health/ready")
    async def readiness():
        return {"status": "ok", "execution_enabled": settings.sandbox_enabled}

    @app.get("/api/models")
    async def models(request: Request):
        try:
            return await request.app.state.manager.catalog.list()
        except (httpx.HTTPError, ValueError, AttributeError):
            raise HTTPException(502, "Model catalog is temporarily unavailable") from None

    @app.get("/api/integrations")
    async def integrations():
        return MCPProvider.integrations

    @app.post("/api/comparisons", status_code=201)
    async def create(request: Request, spec: CreateComparison):
        if request.headers.get("origin") != settings.app_origin:
            raise HTTPException(403, "Unexpected browser origin")
        peer = request.headers.get("x-vb-client") if settings.gateway_secret else None
        request.app.state.limiter.check(peer or request.client.host)
        manager = request.app.state.manager
        await verify_turnstile(settings, manager.client, spec.turnstile_token)
        session, token = await manager.create(spec)
        return {**manager.view(session), "token": token}

    @app.get("/api/comparisons/{session_id}")
    async def comparison(request: Request, session_id: str):
        return request.app.state.manager.view(owned(request, session_id))

    @app.delete("/api/comparisons/{session_id}", status_code=204)
    async def destroy(request: Request, session_id: str):
        await request.app.state.manager.destroy(owned(request, session_id, mutate=True))
        return Response(status_code=204)

    @app.post("/api/comparisons/{session_id}/{side}/stop", status_code=204)
    async def stop(request: Request, session_id: str, side: str):
        session = owned(request, session_id, mutate=True)
        if side not in SIDES:
            raise HTTPException(404, "Agent not found")
        await request.app.state.manager.stop(session, session.runs[side])
        return Response(status_code=204)

    @app.post("/api/comparisons/{session_id}/{side}/instructions", status_code=204)
    async def instruct(request: Request, session_id: str, side: str, instruction: Instruction):
        session = owned(request, session_id, mutate=True)
        if side not in SIDES | {"both"}:
            raise HTTPException(404, "Agent not found")
        runs = list(session.runs.values()) if side == "both" else [session.runs[side]]
        results = await asyncio.gather(
            *(
                request.app.state.manager.follow_up(session, run, instruction.prompt)
                for run in runs
            ),
            return_exceptions=True,
        )
        for run, result in zip(runs, results, strict=True):
            if isinstance(result, HTTPException):
                raise HTTPException(
                    result.status_code, f"Agent {run.side.upper()}: {result.detail}"
                )
            if isinstance(result, Exception):
                raise HTTPException(502, f"Agent {run.side.upper()} could not continue")
        return Response(status_code=204)

    @app.get("/api/comparisons/{session_id}/{side}/export")
    async def export(request: Request, session_id: str, side: str):
        session = owned(request, session_id)
        if side not in SIDES | {"both"}:
            raise HTTPException(404, "Project not found")
        runs = list(session.runs.values()) if side == "both" else [session.runs[side]]
        output = await request.app.state.exporter.collect(runs)
        return Response(
            output,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="vibebench-{side}.zip"',
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/comparisons/{session_id}/{side}/files")
    async def files(request: Request, session_id: str, side: str):
        session = owned(request, session_id)
        if side not in SIDES:
            raise HTTPException(404, "Project not found")
        return await request.app.state.exporter.collect([session.runs[side]], listing=True)

    @app.websocket("/api/comparisons/{session_id}/events")
    async def events(socket: WebSocket, session_id: str):
        if socket.headers.get("origin") != settings.app_origin:
            await socket.close(1008)
            return
        await socket.accept()
        manager = socket.app.state.manager
        try:
            first = await asyncio.wait_for(socket.receive_json(), timeout=5)
            cursor = max(0, int(first.get("after", 0)))
            session = manager.owned(session_id, first.get("token", ""))
            while not session.destroying:
                pending = [event for event in session.events if event["id"] > cursor]
                await asyncio.wait_for(
                    socket.send_json({"session": manager.view(session), "events": pending}),
                    5,
                )
                if pending:
                    cursor = pending[-1]["id"]
                try:
                    message = await asyncio.wait_for(socket.receive(), timeout=1)
                    if message["type"] == "websocket.disconnect":
                        return
                    if message.get("text") == "active":
                        session.activity = asyncio.get_running_loop().time()
                except TimeoutError:
                    continue
            await socket.close(1000)
        except WebSocketDisconnect:
            return
        except (HTTPException, ValueError, TypeError, AttributeError, TimeoutError):
            await socket.close(1008)

    @app.post("/internal/provider/chat/completions")
    async def complete(request: Request):
        return await request.app.state.manager.broker.complete(request)

    return app


app = create_app()
