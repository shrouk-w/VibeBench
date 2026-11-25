from base64 import urlsafe_b64encode
from hashlib import sha256
from secrets import token_hex, token_urlsafe
from time import monotonic
from urllib.parse import urlencode

import httpx

from app.mcp.broker import ENDPOINTS
from app.settings import Settings

AUTH_URL = "https://www.figma.com/oauth/mcp"
TOKEN_URL = "https://api.figma.com/v1/oauth/token"
CALLBACK = "http://127.0.0.1:19876/callback"


class FigmaOAuth:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self.client = client
        self.settings = settings

    async def start(self, comparison):
        verifier = token_urlsafe(48)
        challenge = urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
        comparison.figma_verifier = verifier
        comparison.figma_state = token_hex(32)
        comparison.figma_deadline = monotonic() + 300
        comparison.figma_url = (
            AUTH_URL
            + "?"
            + urlencode(
                {
                    "client_id": self.settings.figma_client_id,
                    "redirect_uri": CALLBACK,
                    "response_type": "code",
                    "scope": "mcp:connect",
                    "state": comparison.figma_state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "resource": ENDPOINTS["figma"],
                }
            )
        )

    async def finish(self, comparison, code) -> str:
        verifier = comparison.figma_verifier
        comparison.figma_verifier = ""
        response = await self.client.post(
            TOKEN_URL,
            data={
                "client_id": self.settings.figma_client_id,
                "client_secret": self.settings.figma_client_secret.get_secret_value(),
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": CALLBACK,
                "resource": ENDPOINTS["figma"],
            },
            timeout=15,
        )
        response.raise_for_status()
        access = response.json()["access_token"]
        if (
            not isinstance(access, str)
            or not access
            or not access.isascii()
            or not access.isprintable()
        ):
            raise ValueError("Invalid Figma access token")
        return access
