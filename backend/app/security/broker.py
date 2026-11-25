from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic

import httpx
from fastapi import HTTPException, Request
from starlette.responses import StreamingResponse

from app.models.catalog import BROKER_ENDPOINTS


@dataclass
class Grant:
    provider: str
    endpoint: str
    model: str
    api_key: str
    expires: float
    remaining: int = 120
    active: bool = False
    address: str = ""


class CredentialBroker:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.grants: dict[str, Grant] = {}

    def issue(self, provider: str, model: str, api_key: str, lifetime: int) -> str:
        token = token_urlsafe(32)
        self.grants[token] = Grant(
            provider,
            BROKER_ENDPOINTS[provider],
            model,
            api_key,
            monotonic() + lifetime,
        )
        return token

    async def complete(self, request: Request, operation: str):
        token = request.headers.get("authorization", "").removeprefix(
            "Bearer "
        ) or request.headers.get("x-api-key", "")
        grant = self.grants.get(token)
        if (
            not grant
            or grant.expires <= monotonic()
            or not grant.active
            or not request.client
            or request.client.host != grant.address
        ):
            raise HTTPException(403, "Invalid or inactive credential grant")
        if grant.remaining <= 0:
            raise HTTPException(429, "Provider request budget exhausted")
        operation_for_provider = {
            "openai": "responses",
            "anthropic": "messages",
        }.get(grant.provider, "chat/completions")
        if operation != operation_for_provider:
            raise HTTPException(403, "Operation is outside the credential grant")
        try:
            payload = await request.json()
        except ValueError as exc:
            raise HTTPException(400, "Invalid provider request") from exc
        if not isinstance(payload, dict) or payload.get("model") != grant.model:
            raise HTTPException(403, "Model is outside the credential grant")
        if "models" in payload or "route" in payload:
            raise HTTPException(403, "Model fallback is outside the credential grant")
        headers = {"Authorization": f"Bearer {grant.api_key}"}
        if grant.provider == "anthropic":
            headers = {"x-api-key": grant.api_key, "anthropic-version": "2023-06-01"}
        if grant.provider == "openai":
            payload["store"] = False
        grant.remaining -= 1
        upstream = self.client.build_request(
            "POST",
            grant.endpoint,
            json=payload,
            headers=headers,
        )
        try:
            response = await self.client.send(upstream, stream=True)
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Provider connection failed") from exc
        if response.is_error:
            await response.aclose()
            code = response.status_code if response.status_code in {400, 401, 403, 429} else 502
            raise HTTPException(code, "Model provider rejected the request")

        async def body():
            # The proxy never forwards provider response headers or error payloads.
            pending = b""
            secret = grant.api_key.encode()
            try:
                async for chunk in response.aiter_bytes():
                    pending += chunk
                    while pending:
                        match = pending.find(secret)
                        safe = max(0, len(pending) - len(secret) + 1)
                        if match >= 0:
                            yield pending[:match] + b"[redacted]"
                            pending = pending[match + len(secret) :]
                        elif safe:
                            yield pending[:safe]
                            pending = pending[safe:]
                        else:
                            break
                if pending:
                    yield pending
            finally:
                await response.aclose()

        media_type = "text/event-stream" if payload.get("stream") else "application/json"
        return StreamingResponse(body(), media_type=media_type)
