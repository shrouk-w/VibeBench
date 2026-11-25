from collections import OrderedDict, deque
from time import monotonic

import httpx
from fastapi import HTTPException


class RateLimiter:
    def __init__(self, limit=8, window=60, clients=1024):
        self.limit = limit
        self.window = window
        self.clients = clients
        self.buckets = OrderedDict()

    def check(self, key):
        now = monotonic()
        bucket = self.buckets.setdefault(key, deque())
        self.buckets.move_to_end(key)
        while len(self.buckets) > self.clients:
            self.buckets.popitem(last=False)
        while bucket and bucket[0] <= now - self.window:
            bucket.popleft()
        if len(bucket) >= self.limit:
            raise HTTPException(429, "Too many attempts. Try again shortly.")
        bucket.append(now)


async def verify_turnstile(settings, client, token):
    if not settings.turnstile_secret:
        return
    if not token:
        raise HTTPException(403, "Complete the Turnstile challenge")
    try:
        response = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.turnstile_secret, "response": token},
            timeout=8,
        )
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, "Turnstile is temporarily unavailable") from None
    if (
        not result.get("success")
        or result.get("hostname") != settings.turnstile_hostname
        or result.get("action") != "comparison"
    ):
        raise HTTPException(403, "Turnstile verification failed")
