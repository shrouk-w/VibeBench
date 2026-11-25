import asyncio

import httpx
import pytest
from fastapi import HTTPException

from app.mcp.registry import MCPProvider
from app.security.requests import RateLimiter, verify_turnstile
from app.settings import Settings


def test_rate_limiter_caps_clients_and_rejects_excess_requests():
    limiter = RateLimiter(limit=2, clients=2)
    limiter.check("first")
    limiter.check("first")
    with pytest.raises(HTTPException, match="429"):
        limiter.check("first")
    limiter.check("second")
    limiter.check("third")
    assert set(limiter.buckets) == {"second", "third"}


def test_mcp_configuration_only_supports_registered_available_tools():
    registry = MCPProvider()
    config = registry.config(["context7"])
    assert config == {
        "context7": {"type": "remote", "url": "https://mcp.context7.com/mcp", "oauth": False}
    }
    for integration in ("https://untrusted.invalid/mcp", "blender"):
        with pytest.raises(ValueError):
            registry.config([integration])


def test_turnstile_checks_hostname_and_action():
    async def check():
        response = {"success": True, "hostname": "localhost", "action": "comparison"}
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json=response))
        settings = Settings(turnstile_secret="test-secret")
        async with httpx.AsyncClient(transport=transport) as client:
            await verify_turnstile(settings, client, "test-token")
            response["action"] = "unrelated"
            with pytest.raises(HTTPException, match="403"):
                await verify_turnstile(settings, client, "test-token")
            response["action"] = "comparison"
            response["hostname"] = "other.invalid"
            with pytest.raises(HTTPException, match="403"):
                await verify_turnstile(settings, client, "test-token")

    asyncio.run(check())
