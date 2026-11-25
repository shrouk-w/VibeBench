import asyncio

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.security.broker import CredentialBroker


def test_broker_scopes_upstream_and_redacts_stream():
    async def check():
        key = "test-provider-secret"
        captured = []

        async def upstream(request):
            captured.append(request)
            return httpx.Response(200, content=b"data: " + key.encode() + b"\n\n")

        async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
            broker = CredentialBroker(client)
            token = broker.issue("openai", "selected", key, 120)
            grant = broker.grants[token]
            grant.active = True
            grant.address = "172.22.0.5"

            def request(body, peer=grant.address):
                async def read():
                    return {"type": "http.request", "body": body}

                return Request(
                    {
                        "type": "http",
                        "method": "POST",
                        "client": (peer, 123),
                        "headers": [(b"authorization", ("Bearer " + token).encode())],
                    },
                    read,
                )

            with pytest.raises(HTTPException, match="403"):
                await broker.complete(request(b"{}", "172.22.0.6"), "responses")
            with pytest.raises(HTTPException, match="403"):
                await broker.complete(request(b'{"model":"selected"}'), "messages")
            with pytest.raises(HTTPException, match="403"):
                await broker.complete(request(b'{"model":"different"}'), "responses")
            with pytest.raises(HTTPException, match="403"):
                await broker.complete(
                    request(b'{"model":"selected","models":["different"]}'), "responses"
                )
            response = await broker.complete(
                request(b'{"model":"selected","stream":true}'), "responses"
            )
            assert (
                b"".join([part async for part in response.body_iterator]) == b"data: [redacted]\n\n"
            )
            assert captured[0].url == httpx.URL("https://api.openai.com/v1/responses")
            assert captured[0].headers["authorization"] == "Bearer " + key
            assert b'"store":false' in captured[0].content
            assert grant.remaining == 119

    asyncio.run(check())
