import asyncio
import json
from time import monotonic

import httpx
import pytest
from fastapi import HTTPException, Request

from app.mcp.broker import RemoteMCPBroker
from app.mcp.registry import MCPProvider


def test_figma_requires_an_oauth_client():
    with pytest.raises(ValueError):
        MCPProvider().validate(["figma"])


def test_mcp_registry_provisions_both_local_and_remote_servers():
    config = MCPProvider(figma_configured=True).config(
        ["context7", "playwright", "figma", "github"],
        {"github": "github-capability", "figma": "figma-capability"},
    )
    assert config["playwright"]["command"][0] == "playwright-mcp"
    assert config["context7"]["url"] == "https://mcp.context7.com/mcp"
    assert config["github"]["headers"]["Authorization"] == "Bearer github-capability"
    assert config["figma"]["url"].endswith("/internal/mcp/figma")


def test_broker_uses_read_only_endpoints_and_binds_each_grant_to_its_sandbox():
    async def check():
        forwarded = []

        async def upstream(request):
            forwarded.append(request)
            return httpx.Response(200, json={"ok": True}, headers={"mcp-session-id": "upstream"})

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            broker = RemoteMCPBroker(client)
            github = broker.issue("github", "github_pat_fixture", monotonic() + 120)
            figma = broker.issue("figma", "figma-fixture", monotonic() + 120)
            for grant in broker.grants.values():
                grant.address = "172.22.0.5"

            def request(token, method, *, peer="172.22.0.5", params=None):
                async def read():
                    return {
                        "type": "http.request",
                        "body": json.dumps(
                            {
                                "method": method,
                                "params": params,
                            }
                        ).encode(),
                    }

                return Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "client": (peer, 123),
                        "headers": [
                            (b"authorization", ("Bearer " + token).encode()),
                            (b"x-mcp-readonly", b"false"),
                        ],
                    },
                    read,
                )

            with pytest.raises(HTTPException, match="403"):
                await broker.forward("github", request(github, "initialize", peer="172.22.0.6"))
            with pytest.raises(HTTPException, match="403"):
                await broker.forward("figma", request(github, "initialize"))
            with pytest.raises(HTTPException, match="403"):
                await broker.forward(
                    "figma",
                    request(
                        figma,
                        "tools/call",
                        params={
                            "name": "use_figma",
                        },
                    ),
                )
            forwarded_response = await broker.forward("github", request(github, "initialize"))
            assert forwarded_response.headers["mcp-session-id"] == "upstream"
            assert b"".join([part async for part in forwarded_response.body_iterator])
            with pytest.raises(HTTPException, match="403"):
                await broker.forward("github", request(github, "tools/list"))
            assert len(forwarded) == 1
            assert str(forwarded[0].url) == "https://api.githubcopilot.com/mcp/readonly"
            assert forwarded[0].headers["x-mcp-readonly"] == "true"
            assert forwarded[0].headers["authorization"] == "Bearer github_pat_fixture"

    asyncio.run(check())
