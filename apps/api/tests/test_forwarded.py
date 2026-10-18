import httpx
import pytest
from fastapi import FastAPI, Request

from clinic_api.forwarded import ForwardedClient


def _app(hops: int) -> FastAPI:
    app = FastAPI()

    @app.get("/who")
    async def who(request: Request):
        return {"client": request.client.host}

    app.add_middleware(ForwardedClient, hops=hops)
    return app


async def _who(hops: int, forwarded: str | None) -> str:
    headers = {"X-Forwarded-For": forwarded} if forwarded is not None else {}
    transport = httpx.ASGITransport(app=_app(hops), client=("10.0.0.9", 1234))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return (await c.get("/who", headers=headers)).json()["client"]


@pytest.mark.parametrize(
    ("hops", "header", "expected"),
    [
        (1, "203.0.113.7", "203.0.113.7"),  # one proxy added the real address
        (1, "198.51.100.1, 203.0.113.7", "203.0.113.7"),  # a client-supplied entry on the left is ignored
        (1, "1.1.1.1, 2.2.2.2, 203.0.113.7", "203.0.113.7"),
        (2, "198.51.100.1, 203.0.113.7, 35.1.1.1", "203.0.113.7"),  # two trusted proxies: skip the last one too
        (1, "2001:db8::1", "2001:db8::1"),
        (0, "203.0.113.7", "10.0.0.9"),  # trusting nobody: the header is ignored
        (1, None, "10.0.0.9"),  # no header: the connection's own address
        (2, "203.0.113.7", "10.0.0.9"),  # fewer entries than proxies: do not guess
        (1, "not-an-ip", "10.0.0.9"),
        (1, " , ", "10.0.0.9"),
    ],
)
async def test_the_client_is_found_by_counting_trusted_proxies_from_the_right(hops, header, expected):
    assert await _who(hops, header) == expected
