import asyncio
import hashlib
import json
from secrets import compare_digest, token_hex, token_urlsafe
from time import monotonic

import httpx
from docker.errors import DockerException
from fastapi import HTTPException

from app.agents.opencode import PREVIEW_GUIDANCE, AgentProvider
from app.mcp.registry import MCPProvider
from app.models.catalog import ModelProvider
from app.sandboxes.docker_provider import SandboxProvider
from app.security.broker import CredentialBroker
from app.sessions.types import Comparison, CreateComparison, Run, Status
from app.settings import Settings

BROKER_PROVIDER = "vb-byok"


class SessionManager:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient,
        catalog: ModelProvider,
        mcp: MCPProvider,
        broker: CredentialBroker,
        sandboxes: SandboxProvider | None,
        agents: AgentProvider,
    ):
        self.settings = settings
        self.client = client
        self.catalog = catalog
        self.mcp = mcp
        self.broker = broker
        self.sandboxes = sandboxes
        self.agents = agents
        self.sessions: dict[str, Comparison] = {}
        self.previews: dict[str, tuple[Comparison, Run]] = {}
        self.cleanup_lock = asyncio.Lock()

    async def create(self, request: CreateComparison) -> tuple[Comparison, str]:
        if self.sandboxes is None:
            raise HTTPException(503, "Docker execution is disabled")
        if len(self.sessions) >= self.settings.max_sessions:
            raise HTTPException(429, "All comparison slots are in use")
        try:
            config = self.mcp.config(request.integrations)
            models = {(model.provider, model.id): model for model in await self.catalog.list()}
        except (httpx.HTTPError, AttributeError):
            raise HTTPException(502, "Model catalog is temporarily unavailable") from None
        except ValueError:
            raise HTTPException(422, "Invalid integration or provider data") from None
        if len(self.sessions) >= self.settings.max_sessions:
            raise HTTPException(429, "All comparison slots are in use")
        selections = []
        for choice in request.models:
            model = models.get((choice.provider, choice.model))
            if not model or not model.available:
                raise HTTPException(422, "Selected model is unavailable")
            key = choice.api_key.get_secret_value().strip() if choice.api_key else ""
            if model.requires_key and (not 8 <= len(key) <= 512 or not key.isascii()):
                raise HTTPException(422, "Enter a valid provider API key")
            if model.requires_key and any(ord(char) <= 32 or ord(char) >= 127 for char in key):
                raise HTTPException(422, "Enter a valid provider API key")
            selections.append((model, key))
        runs = {}
        for side, (model, key) in zip(("a", "b"), selections, strict=True):
            grant = None
            if model.requires_key:
                grant = self.broker.issue(
                    model.provider, model.id, key, self.settings.lifetime_seconds
                )
            runs[side] = Run(side, model, token_hex(24), token_urlsafe(32), grant)
        token = token_urlsafe(32)
        session = Comparison(
            token_hex(12),
            hashlib.sha256(token.encode()).digest(),
            request.prompt,
            request.integrations,
            runs,
        )
        self.sessions[session.id] = session
        for run in runs.values():
            self.previews[run.capability] = (session, run)
            self.spawn(session, self.provision(session, run, config), provisioning=True)
        return session, token

    def owned(self, session_id: str, token: str) -> Comparison:
        session = self.sessions.get(session_id)
        digest = hashlib.sha256(token.encode()).digest()
        if not session or session.destroying or not compare_digest(digest, session.token_digest):
            raise HTTPException(404, "Comparison not found")
        session.activity = monotonic()
        return session

    def spawn(self, session, coroutine, *, provisioning=False):
        task = asyncio.create_task(coroutine)
        group = session.provisioning if provisioning else session.tasks
        group.add(task)
        task.add_done_callback(group.discard)

    def emit(self, session: Comparison, run: Run, kind: str, text: str):
        secrets = [session.runs[side].password for side in session.runs]
        for item in session.runs.values():
            if item.grant:
                secrets.extend((item.grant, self.broker.grants[item.grant].api_key))
        for value in secrets:
            text = text.replace(value, "[redacted]")
        session.sequence += 1
        session.events.append(
            {"id": session.sequence, "side": run.side, "kind": kind, "text": text[:4000]}
        )

    def status(self, session, run, state, note=""):
        run.status = state
        self.emit(session, run, "status", note or state.value)
        if run.grant:
            self.broker.grants[run.grant].active = state == Status.RUNNING

    def environment(self, run, mcp_config):
        provider = run.model.provider
        config = {
            "model": f"{provider}/{run.model.id}",
            "share": "disabled",
            "autoupdate": False,
            "mcp": mcp_config,
            "permission": {"*": "allow", "external_directory": "deny"},
        }
        if run.grant:
            provider = BROKER_PROVIDER
            config["model"] = f"{provider}/{run.model.id}"
            config["provider"] = {
                provider: {
                    "npm": "@ai-sdk/openai-compatible",
                    "name": run.model.provider_name,
                    "options": {
                        "baseURL": "http://vb-broker.invalid/internal/provider",
                        "apiKey": run.grant,
                    },
                    "models": {run.model.id: {"name": run.model.name, "tool_call": True}},
                }
            }
        config["enabled_providers"] = [provider]
        return {
            "OPENCODE_CONFIG_CONTENT": json.dumps(config),
            "OPENCODE_SERVER_PASSWORD": run.password,
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
        }, provider

    async def provision(self, session, run, mcp_config):
        self.status(session, run, Status.PROVISIONING)
        try:
            environment, provider = self.environment(run, mcp_config)
            run.sandbox = await self.sandboxes.create(f"vb-{session.id}-{run.side}", environment)
            if session.destroying:
                return
            if run.grant:
                self.broker.grants[run.grant].address = run.sandbox.address
            run.agent = await self.agents.connect(
                run.sandbox,
                run.password,
                provider,
                run.model.id,
            )
            if session.destroying:
                return
            connected = asyncio.Event()
            self.spawn(session, self.watch_events(session, run, connected))
            self.spawn(session, self.watch_preview(session, run))
            await asyncio.wait_for(connected.wait(), timeout=15)
            if session.destroying:
                return
            self.status(session, run, Status.RUNNING, "Agent started")
            await self.agents.prompt(run.agent, f"{session.prompt}\n\n{PREVIEW_GUIDANCE}")
        except (httpx.HTTPError, TimeoutError, ValueError):
            if not session.destroying:
                self.status(session, run, Status.FAILED, "OpenCode could not start this model")
                if not run.agent and run.sandbox:
                    await self.release(run)
        except DockerException:
            if not session.destroying:
                self.status(session, run, Status.FAILED, "Sandbox provisioning failed")

    async def release(self, run):
        if run.sandbox:
            await self.sandboxes.destroy(run.sandbox)
            run.sandbox = None

    async def watch_events(self, session, run, connected):
        while not session.destroying:
            try:
                async for event in self.agents.events(run.agent, connected):
                    self.handle_event(session, run, event)
            except (httpx.HTTPError, ValueError):
                if not session.destroying:
                    self.emit(session, run, "activity", "Agent event stream disconnected")
            await asyncio.sleep(1)

    def handle_event(self, session, run, event):
        kind = event.get("type")
        props = event.get("properties", {})
        part = props.get("part", {})
        if (props.get("sessionID") or part.get("sessionID")) != run.agent.session_id:
            return
        if kind == "session.error" and run.status == Status.RUNNING and not run.stopping:
            error = props.get("error", {})
            message = error.get("data", {}).get("message") or "Model execution failed"
            self.status(session, run, Status.FAILED, str(message))
        elif kind == "session.idle" and run.status == Status.RUNNING and not run.stopping:
            self.status(session, run, Status.READY, "Agent finished")
        elif kind == "message.part.delta" and props.get("field") == "text":
            self.emit(session, run, "response", str(props.get("delta", "")))
        elif kind == "message.part.updated" and part.get("type") == "tool":
            tool = part.get("tool", "tool")
            state = part.get("state", {})
            step = state.get("status", "")
            if step in {"running", "completed", "error"}:
                self.emit(session, run, "activity", f"{tool} · {step}")
            if tool == "bash" and step in {"completed", "error"}:
                self.emit(
                    session, run, "terminal", str(state.get("output") or state.get("error", ""))
                )
            if tool in {"edit", "write", "apply_patch"} and step == "completed":
                self.emit(session, run, "files", str(state.get("title") or tool))

    async def watch_preview(self, session, run):
        while not session.destroying:
            available = False
            try:
                response = await self.client.head(run.sandbox.url(4173), timeout=2)
                available = response.status_code < 500
            except httpx.HTTPError:
                pass
            if available != run.preview:
                run.preview = available
                self.emit(
                    session,
                    run,
                    "preview",
                    "Application server ready" if available else "Preview disconnected",
                )
            await asyncio.sleep(2)

    async def follow_up(self, session, run, text):
        if (
            not run.agent
            or run.stopping
            or run.status
            not in {
                Status.STOPPED,
                Status.READY,
                Status.FAILED,
            }
        ):
            raise HTTPException(409, "Agent must be stopped or finished before continuing")
        self.status(session, run, Status.RUNNING, "Agent resumed")
        try:
            await self.agents.prompt(run.agent, f"{text}\n\n{PREVIEW_GUIDANCE}")
        except httpx.HTTPError:
            if not session.destroying:
                self.status(session, run, Status.FAILED, "OpenCode rejected the instruction")
            raise HTTPException(502, "OpenCode rejected the instruction") from None

    async def stop(self, session, run):
        if not run.agent or run.status != Status.RUNNING or run.stopping:
            raise HTTPException(409, "Agent is not running")
        run.stopping = True
        try:
            await self.agents.abort(run.agent)
            if not session.destroying:
                self.status(session, run, Status.STOPPED, "Agent stopped")
        except httpx.HTTPError:
            raise HTTPException(502, "OpenCode could not stop the agent") from None
        finally:
            run.stopping = False

    async def destroy(self, session):
        async with self.cleanup_lock:
            if session.id not in self.sessions:
                return
            session.destroying = True
            await asyncio.gather(*session.provisioning, return_exceptions=True)
            tasks = tuple(session.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for run in session.runs.values():
                self.previews.pop(run.capability, None)
                if run.grant:
                    self.broker.grants.pop(run.grant, None)
                    run.grant = None
                run.status = Status.DESTROYED
            results = await asyncio.gather(
                *(self.release(run) for run in session.runs.values()),
                return_exceptions=True,
            )
            if any(isinstance(result, Exception) for result in results):
                raise HTTPException(503, "Cleanup will be retried")
            del self.sessions[session.id]

    def remaining(self, session):
        now = monotonic()
        return max(
            0,
            int(
                min(
                    session.created + self.settings.lifetime_seconds - now,
                    session.activity + self.settings.idle_seconds - now,
                )
            ),
        )

    async def reap(self):
        while True:
            await asyncio.sleep(5)
            for session in list(self.sessions.values()):
                if session.destroying or not self.remaining(session):
                    try:
                        await self.destroy(session)
                    except HTTPException:
                        continue

    def view(self, session):
        origin = "http"
        port = f":{self.settings.preview_port}"
        return {
            "id": session.id,
            "expires_in": self.remaining(session),
            "runs": {
                side: {
                    "model": run.model.name,
                    "provider": run.model.provider_name,
                    "status": run.status,
                    "preview_url": f"{origin}://vb-{run.capability}.{self.settings.preview_domain}{port}"
                    if run.preview
                    else None,
                }
                for side, run in session.runs.items()
            },
        }
