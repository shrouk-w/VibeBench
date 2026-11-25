import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.sandboxes.docker_provider import Sandbox

PREVIEW_GUIDANCE = (
    "Build the web app in /workspace. Run its application server in the background with "
    "nohup and redirected output on 0.0.0.0 port 4173. Allow the incoming preview Host "
    "header if your framework validates it. Verify the app serves HTTP on that port "
    "before finishing. Leave the server running so the user can interact with it. "
    "Keep generated source and assets in /workspace."
)


@dataclass(frozen=True)
class Agent:
    base: str
    session_id: str
    password: str
    provider: str
    model: str

    @property
    def auth(self):
        return ("opencode", self.password)


class AgentProvider(Protocol):
    async def connect(
        self, sandbox: Sandbox, password: str, provider: str, model: str
    ) -> Agent: ...
    async def prompt(self, agent: Agent, text: str) -> None: ...
    async def abort(self, agent: Agent) -> None: ...
    def events(self, agent: Agent, connected: asyncio.Event) -> AsyncIterator[dict]: ...


class OpenCodeAgentProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def connect(self, sandbox, password, provider, model):
        base = sandbox.url(4096)
        auth = ("opencode", password)
        async with asyncio.timeout(75):
            while True:
                try:
                    response = await self.client.get(f"{base}/global/health", auth=auth, timeout=2)
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    await asyncio.sleep(0.75)
        response = await self.client.get(f"{base}/provider", auth=auth)
        response.raise_for_status()
        candidates = response.json().get("all", [])
        if not any(item["id"] == provider and model in item["models"] for item in candidates):
            raise ValueError("Selected model is absent from OpenCode provider discovery")
        response = await self.client.post(
            f"{base}/session", auth=auth, json={"title": "VibeBench comparison"}
        )
        response.raise_for_status()
        return Agent(base, response.json()["id"], password, provider, model)

    async def prompt(self, agent, text):
        response = await self.client.post(
            f"{agent.base}/session/{agent.session_id}/prompt_async",
            auth=agent.auth,
            json={
                "model": {"providerID": agent.provider, "modelID": agent.model},
                "parts": [{"type": "text", "text": text}],
            },
        )
        response.raise_for_status()

    async def abort(self, agent):
        response = await self.client.post(
            f"{agent.base}/session/{agent.session_id}/abort", auth=agent.auth
        )
        response.raise_for_status()

    async def events(self, agent, connected):
        timeout = httpx.Timeout(15, read=None)
        async with self.client.stream(
            "GET", f"{agent.base}/event", auth=agent.auth, timeout=timeout
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event.get("type") == "server.connected":
                    connected.set()
                else:
                    yield event
