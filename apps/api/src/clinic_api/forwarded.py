"""Find the real client address behind a proxy such as Cloud Run.

Every request through Cloud Run appears to come from Google's front end, so without this the login rate limit
(counted per client address) would be shared by all users at once. X-Forwarded-For cannot be trusted whole: a
client can send its own, and each proxy appends the address it saw. So we count in from the right and trust only
as many entries as there are proxies we run behind.
"""

import ipaddress


class ForwardedClient:
    """ASGI middleware: set ``scope["client"]`` from the entry ``hops`` places from the right of X-Forwarded-For."""

    def __init__(self, app, hops: int):
        self.app, self.hops = app, hops

    async def __call__(self, scope, receive, send):
        if self.hops and scope["type"] in ("http", "websocket"):
            client = self._client(scope)
            if client:
                scope = {**scope, "client": (client, 0)}
        await self.app(scope, receive, send)

    def _client(self, scope) -> str | None:
        raw = next((v for k, v in scope["headers"] if k == b"x-forwarded-for"), b"").decode("latin-1")
        entries = [part.strip() for part in raw.split(",") if part.strip()]
        if len(entries) < self.hops:
            return None  # fewer proxies than expected: keep the connection's own address
        try:
            return str(ipaddress.ip_address(entries[-self.hops]))
        except ValueError:
            return None
