import asyncio
import hashlib
import json
from secrets import compare_digest, token_hex, token_urlsafe
from time import monotonic
from urllib.parse import urlsplit

import httpx
from docker.errors import DockerException
from fastapi import HTTPException

from app.agents.opencode import PREVIEW_GUIDANCE, AgentProvider
from app.mcp.broker import RemoteMCPBroker
from app.mcp.figma import FigmaOAuth
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
        self.mcp_broker = RemoteMCPBroker(client)
        self.figma = FigmaOAuth(client, settings)
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
            self.mcp.validate(request.integrations)
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
        github_key = request.github_token.get_secret_value().strip() if request.github_token else ""
        if "github" in request.integrations and (
            not github_key.startswith("github_pat_")
            or not 20 <= len(github_key) <= 512
            or not all(char.isascii() and (char.isalnum() or char == "_") for char in github_key)
        ):
            raise HTTPException(422, "Enter a fine-grained GitHub personal access token")
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
        if "github" in session.integrations:
            self.issue_mcp_grants(session, "github", github_key)
        if "figma" in session.integrations:
            await self.figma.start(session)
        else:
            self.launch(session)
        return session, token

    def issue_mcp_grants(self, session, name, key):
        expires = session.created + self.settings.lifetime_seconds
        for run in session.runs.values():
            run.mcp_grants[name] = self.mcp_broker.issue(name, key, expires)

    def launch(self, session):
        for run in session.runs.values():
            self.previews[run.capability] = (session, run)
            config = self.mcp.config(session.integrations, run.mcp_grants)
            self.spawn(session, self.provision(session, run, config), provisioning=True)

    async def finish_figma(self, state, code):
        session = next(
            (
                item
                for item in self.sessions.values()
                if not item.destroying
                and item.figma_state
                and compare_digest(item.figma_state, state)
            ),
            None,
        )
        if not session or monotonic() >= session.figma_deadline:
            return False
        session.figma_state = ""
        session.figma_url = ""
        session.activity = monotonic()
        try:
            if not code:
                raise ValueError("Figma sign-in was cancelled")
            key = await self.figma.finish(session, code)
            if session.destroying:
                return False
            self.issue_mcp_grants(session, "figma", key)
        except (httpx.HTTPError, ValueError, KeyError):
            session.figma_verifier = ""
            session.figma_error = "Figma could not connect. End the session to retry."
            return False
        if session.destroying:
            return False
        self.launch(session)
        return True

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
            for grant in item.mcp_grants.values():
                secrets.extend((grant, self.mcp_broker.grants[grant].key))
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
                    "npm": {
                        "openai": "@ai-sdk/openai",
                        "anthropic": "@ai-sdk/anthropic",
                    }.get(run.model.provider, "@ai-sdk/openai-compatible"),
                    "name": run.model.provider_name,
                    "options": {
                        "baseURL": "http://vb-broker.invalid/internal/provider",
                        "apiKey": run.grant,
                    },
                    "models": {run.model.id: {"name": run.model.name, "tool_call": True}},
                }
            }
        config["enabled_providers"] = [provider]
        config["small_model"] = config["model"]
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
            for grant in run.mcp_grants.values():
                self.mcp_broker.grants[grant].address = run.sandbox.address
            run.agent = await self.agents.connect(
                run.sandbox,
                run.password,
                provider,
                run.model.id,
            )
            if session.destroying:
                return
            if mcp_config:
                states = await self.agents.mcp_status(run.agent)
                failed = [
                    name for name in mcp_config if states.get(name, {}).get("status") != "connected"
                ]
                if failed:
                    self.status(
                        session, run, Status.FAILED, "MCP could not connect: " + ", ".join(failed)
                    )
                    run.agent = None
                    await self.release(run)
                    return
                self.emit(session, run, "activity", "MCP connected: " + ", ".join(mcp_config))
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
                    await self.handle_event(session, run, event)
            except (httpx.HTTPError, ValueError):
                if not session.destroying:
                    self.emit(session, run, "activity", "Agent event stream disconnected")
            await asyncio.sleep(1)

    async def handle_event(self, session, run, event):
        kind = event.get("type")
        props = event.get("properties", {})
        part = props.get("part", {})
        if (props.get("sessionID") or part.get("sessionID")) != run.agent.session_id:
            return
        if kind == "session.status" and run.status == Status.RUNNING and not run.stopping:
            status = props.get("status", {})
            if status.get("type") == "retry":
                message = str(status.get("message", "Provider requested a retry"))
                if "Free usage exceeded" in message or status.get("attempt", 0) >= 3:
                    run.stopping = True
                    try:
                        await self.agents.abort(run.agent)
                    except httpx.HTTPError:
                        self.emit(session, run, "activity", "OpenCode could not cancel its retry")
                    finally:
                        run.stopping = False
                    if not session.destroying:
                        note = (
                            "OpenCode free usage limit reached"
                            if "Free usage exceeded" in message
                            else message
                        )
                        self.status(session, run, Status.FAILED, note)
                else:
                    self.emit(session, run, "activity", message)
        elif kind == "session.error" and run.status == Status.RUNNING and not run.stopping:
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
                Status.RUNNING,
                Status.STOPPED,
                Status.READY,
                Status.FAILED,
            }
        ):
            raise HTTPException(409, "Agent is unavailable for follow-up instructions")
        was_running = run.status == Status.RUNNING
        if not was_running:
            self.status(session, run, Status.RUNNING, "Agent resumed")
        try:
            await self.agents.prompt(run.agent, f"{text}\n\n{PREVIEW_GUIDANCE}")
            if was_running:
                self.emit(session, run, "activity", "Follow-up sent")
        except httpx.HTTPError:
            if not session.destroying and not was_running:
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
                for token in run.mcp_grants.values():
                    self.mcp_broker.grants.pop(token, None)
                run.mcp_grants.clear()
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
                elif session.figma_state and monotonic() >= session.figma_deadline:
                    session.figma_state = ""
                    session.figma_url = ""
                    session.figma_verifier = ""
                    session.figma_error = "Figma sign-in expired. End the session to retry."

    def view(self, session):
        scheme = urlsplit(self.settings.app_origin).scheme
        default_port = 443 if scheme == "https" else 80
        port = (
            "" if self.settings.preview_port == default_port else f":{self.settings.preview_port}"
        )
        return {
            "id": session.id,
            "expires_in": self.remaining(session),
            "figma": {
                "url": session.figma_url,
                "error": session.figma_error,
            }
            if "figma" in session.integrations
            and all(run.status == Status.CREATED for run in session.runs.values())
            else None,
            "runs": {
                side: {
                    "model": run.model.name,
                    "provider": run.model.provider_name,
                    "status": run.status,
                    "preview_url": f"{scheme}://vb-{run.capability}.{self.settings.preview_domain}{port}"
                    if run.preview
                    else None,
                }
                for side, run in session.runs.items()
            },
        }
