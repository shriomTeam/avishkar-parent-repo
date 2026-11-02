"""The guard in conftest.py: no test can reach the real network, so none can send a real SMS."""

import httpx
import pytest
from fastapi import FastAPI

from clinic_lead_response.gateway.provider import ProviderRequest
from clinic_lead_response.gateway.twilio import TwilioProvider


async def test_a_real_async_client_is_refused():
    with pytest.raises(AssertionError, match="real network"):
        async with httpx.AsyncClient() as client:
            await client.get("https://api.twilio.com/")


def test_a_real_sync_client_is_refused():
    with pytest.raises(AssertionError, match="real network"), httpx.Client() as client:
        client.get("https://api.twilio.com/")


async def test_a_provider_built_without_a_fake_transport_fails_loudly_instead_of_texting():
    import uuid

    real = TwilioProvider("ACx", "secret")  # no transport injected: a test that forgot to fake Twilio
    request = ProviderRequest("+14155550142", "+14155550100", "hi", uuid.uuid4(), 1, uuid.uuid4())
    with pytest.raises(AssertionError, match="real network"):
        await real.send(request)


async def test_fake_transports_still_work():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True}))) as c:
        assert (await c.get("https://example.test/")).json() == {"ok": True}
    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/ping")).json() == {"ok": True}
