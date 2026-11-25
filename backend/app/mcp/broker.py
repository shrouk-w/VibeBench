from dataclasses import dataclass
from secrets import token_urlsafe
from time import monotonic

import httpx
from fastapi import HTTPException, Request, Response
from fastapi.responses import StreamingResponse

ENDPOINTS = {
    "github": "https://api.githubcopilot.com/mcp/readonly",
    "figma": "https://mcp.figma.com/mcp",
}
FIGMA_TOOLS = {
    "get_design_context",
    "get_screenshot",
    "get_metadata",
    "get_variable_defs",
    "get_code_connect_map",
    "get_code_connect_suggestions",
    "get_figjam",
}
MCP_METADATA = {"mcp-protocol-version", "mcp-session-id", "last-event-id"}
MCP_METHODS = {
    "initialize",
    "ping",
    "notifications/initialized",
    "notifications/cancelled",
    "tools/list",
    "tools/call",
    "resources/list",
    "resources/templates/list",
    "resources/read",
    "prompts/list",
}


@dataclass
class Grant:
    name: str
    key: str
    expires: float
    address: str = ""
    session_id: str = ""
    remaining: int = 120


class RemoteMCPBroker:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.grants: dict[str, Grant] = {}

    def issue(self, name: str, key: str, expires: float) -> str:
        token = token_urlsafe(32)
        self.grants[token] = Grant(name, key, expires)
        return token

    async def forward(self, name: str, request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        grant = self.grants.get(token)
        if (
            not grant
            or grant.name != name
            or grant.expires <= monotonic()
            or (not request.client or request.client.host != grant.address)
        ):
            raise HTTPException(403, "Invalid MCP grant")
        if request.method == "GET":
            return Response(status_code=405, headers={"Allow": "POST"})
        if grant.remaining <= 0:
            raise HTTPException(429, "MCP request budget exhausted")
        if request.headers.get("mcp-session-id", "") != grant.session_id:
            raise HTTPException(403, "Invalid MCP session")
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(400, "Invalid MCP request") from None
        method = payload.get("method") if isinstance(payload, dict) else None
        if not isinstance(method, str) or method not in MCP_METHODS:
            raise HTTPException(403, "MCP method unavailable")
        if name == "figma" and method == "tools/call":
            params = payload.get("params")
            tool = params.get("name") if isinstance(params, dict) else None
            if not isinstance(tool, str) or tool not in FIGMA_TOOLS:
                raise HTTPException(403, "Figma tool unavailable")
        grant.remaining -= 1
        headers = {key: value for key, value in request.headers.items() if key in MCP_METADATA}
        headers.update(
            {
                "Authorization": f"Bearer {grant.key}",
                "Accept": "application/json, text/event-stream",
            }
        )
        if name == "github":
            headers.update(
                {"X-MCP-Readonly": "true", "X-MCP-Toolsets": "repos,issues,pull_requests"}
            )
        try:
            upstream = self.client.build_request(
                "POST", ENDPOINTS[name], headers=headers, json=payload
            )
            response = await self.client.send(upstream, stream=True)
        except httpx.HTTPError:
            raise HTTPException(502, "MCP service is unavailable") from None
        if response.is_error or response.is_redirect:
            await response.aclose()
            status = (
                response.status_code if response.status_code in {400, 401, 403, 404, 429} else 502
            )
            return Response(status_code=status)
        if session_id := response.headers.get("mcp-session-id"):
            grant.session_id = session_id
        safe_headers = {
            key: value
            for key, value in response.headers.items()
            if key
            in (
                "content-type",
                "mcp-session-id",
                "mcp-protocol-version",
            )
        }
        if response.status_code in {202, 204}:
            await response.aclose()
            return Response(status_code=response.status_code, headers=safe_headers)

        async def stream():
            remaining = 16 * 1024 * 1024
            try:
                async for chunk in response.aiter_bytes():
                    remaining -= len(chunk)
                    if remaining < 0 or token not in self.grants:
                        break
                    yield chunk
            finally:
                await response.aclose()

        return StreamingResponse(stream(), status_code=response.status_code, headers=safe_headers)
