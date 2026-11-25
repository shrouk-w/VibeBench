from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import httpx


@dataclass(frozen=True)
class Model:
    provider: str
    id: str
    provider_name: str
    name: str
    free: bool
    requires_key: bool
    available: bool


class ModelProvider(Protocol):
    async def list(self) -> list[Model]: ...


BROKER_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
}
PROVIDERS = {"opencode", "openai", "anthropic", *BROKER_ENDPOINTS}


class ModelsDevProvider:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.cached: list[Model] | None = None
        self.refresh_after = 0.0
        self.lock = asyncio.Lock()

    async def list(self) -> list[Model]:
        async with self.lock:
            if self.cached is not None and monotonic() < self.refresh_after:
                return self.cached
            try:
                response, live = await asyncio.gather(
                    self.client.get("https://models.dev/api.json", timeout=12),
                    self.client.get("https://opencode.ai/zen/v1/models", timeout=12),
                )
                response.raise_for_status()
                live.raise_for_status()
                active = {item["id"] for item in live.json()["data"]}
                models = self.parse(response.json(), active)
            except (httpx.HTTPError, ValueError, AttributeError):
                if self.cached is not None:
                    return self.cached
                raise
            self.cached = models
            self.refresh_after = monotonic() + 300
            return models

    @staticmethod
    def parse(providers: dict, active: set[str]) -> list[Model]:
        models = []
        for provider in sorted(PROVIDERS & providers.keys()):
            entry = providers[provider]
            for identifier, model in entry.get("models", {}).items():
                if not model.get("tool_call") or model.get("status") == "deprecated":
                    continue
                cost = model.get("cost") or {}
                free = provider == "opencode" and cost.get("input") == cost.get("output") == 0
                if provider == "opencode" and not (free and identifier in active):
                    continue
                models.append(
                    Model(
                        provider,
                        identifier,
                        entry["name"],
                        model["name"],
                        free,
                        provider != "opencode",
                        free or provider in BROKER_ENDPOINTS,
                    )
                )
        return sorted(models, key=lambda model: (not model.free, model.provider, model.name))
