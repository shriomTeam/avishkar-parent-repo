import json
import random

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.ops import AuditLog
from clinic_db.models.voice import PhoneNumber
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.router import router as inbound_router
from clinic_voice_receptionist.numbers import service
from clinic_voice_receptionist.numbers.router import router as numbers_router
from clinic_voice_receptionist.numbers.twilio import TwilioError, TwilioNumbers
from clinic_voice_receptionist.testing import FakeNumbers

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(inbound_router)
app.include_router(numbers_router)


def _random_number(area: str | None = None) -> str:
    """Numbers are unique across the whole database and the test database keeps its rows, so every test gets its own."""
    area = area or f"{random.randint(2, 9)}{random.randint(0, 99):02d}"
    exchange = f"{random.randint(2, 9)}{random.randint(0, 99):02d}"
    return f"+1{area}{exchange}{random.randint(0, 9999):04d}"


@pytest.fixture
def num():
    return _random_number()


@pytest.fixture
def num2():
    return _random_number()


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


@pytest.fixture
async def client():
    app.state.twilio_numbers = FakeNumbers()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def twilio():
    return app.state.twilio_numbers


async def _agent(client, tenant, name="Front desk", **extra):
    body = {"name": name, "prompt": "Answer calls kindly.", "fields": []} | extra
    r = await client.post("/inbound/agents", json=body, headers=_h(tenant))
    assert r.status_code == 201, r.text
    return r.json()


async def _buy(client, tenant, number, **extra):
    return await client.post("/inbound/numbers", json={"number": number} | extra, headers=_h(tenant))


# ---- search ----------------------------------------------------------------------------------------------


async def test_search_returns_numbers_and_passes_filters(client, twilio):
    t = await create_test_tenant()
    r = await client.get("/inbound/numbers/available?area_code=212&contains=555", headers=_h(t))
    assert r.status_code == 200 and r.json()[0]["number"].startswith("+1212555")
    assert twilio.calls == [("search", "local", "212", "555")]
    toll = await client.get("/inbound/numbers/available?kind=toll_free", headers=_h(t))
    assert toll.json()[0]["kind"] == "toll_free"


@pytest.mark.parametrize(
    "query", ["area_code=1234", "area_code=abc", "contains=12%27--", "kind=mobile", "area_code=055"]
)
async def test_search_rejects_odd_input(client, query):
    t = await create_test_tenant()
    assert (await client.get(f"/inbound/numbers/available?{query}", headers=_h(t))).status_code == 422


async def test_only_managers_can_search_buy_assign_or_release(client, num):
    t = await create_test_tenant()
    desk = _h(t, "front_desk")
    assert (await client.get("/inbound/numbers/available", headers=desk)).status_code == 403
    assert (await client.post("/inbound/numbers", json={"number": num}, headers=desk)).status_code == 403
    assert (await client.get("/inbound/numbers", headers=desk)).status_code == 200  # reading is fine


# ---- buying ----------------------------------------------------------------------------------------------


async def test_buying_records_the_number_and_is_audited(client, twilio, num):
    t = await create_test_tenant()
    r = await _buy(client, t, num)
    assert r.status_code == 201 and r.json()["number"] == num and r.json()["kind"] == "local"
    assert list(twilio.owned.values()) == [num]
    listing = (await client.get("/inbound/numbers", headers=_h(t))).json()
    assert [n["number"] for n in listing["numbers"]] == [num] and listing["enabled"] is True
    async with tenant_session(t) as s:
        actions = (await s.scalars(select(AuditLog.action).where(AuditLog.entity_type == "voice.phone_number"))).all()
    assert "voice.number.purchased" in actions


async def test_a_toll_free_number_is_recognised(client):
    t = await create_test_tenant()
    r = await _buy(client, t, _random_number("800"))
    assert r.json()["kind"] == "toll_free"


@pytest.mark.parametrize("number", ["4155550101", "+442071234567", "+1415555", "+11555550101", "'; DROP TABLE x;--"])
async def test_only_us_numbers_can_be_bought(client, twilio, number):
    t = await create_test_tenant()
    r = await _buy(client, t, number)
    assert r.status_code == 422 and twilio.owned == {}


async def test_a_clinic_cannot_go_over_its_limit(client, twilio, monkeypatch, num2, num):
    monkeypatch.setenv("VOICE_MAX_NUMBERS_PER_CLINIC", "1")
    get_voice_settings.cache_clear()
    try:
        t = await create_test_tenant()
        assert (await _buy(client, t, num)).status_code == 201
        second = await _buy(client, t, num2)
        assert second.status_code == 409 and "up to 1" in second.json()["detail"]
        assert len(twilio.owned) == 1  # nothing was bought for the refused request
    finally:
        monkeypatch.delenv("VOICE_MAX_NUMBERS_PER_CLINIC")
        get_voice_settings.cache_clear()


async def test_twilio_errors_are_shown_and_nothing_is_saved(client, twilio, num):
    t = await create_test_tenant()
    twilio.fail_next_buy = "The number is no longer available."
    r = await _buy(client, t, num)
    assert r.status_code == 409 and "no longer available" in r.json()["detail"]
    assert (await client.get("/inbound/numbers", headers=_h(t))).json()["numbers"] == []


async def test_a_purchase_that_cannot_be_saved_is_given_back(client, twilio, num):
    a, b = await create_test_tenant(), await create_test_tenant()
    assert (await _buy(client, a, num)).status_code == 201
    clash = await _buy(client, b, num)  # the same number cannot belong to two clinics
    assert clash.status_code == 409
    assert list(twilio.owned.values()) == [num]  # the second purchase was released again
    assert [c[0] for c in twilio.calls].count("release") == 1


async def test_without_twilio_set_up_the_screen_says_so(client, monkeypatch):
    # A developer's .env may hold real Twilio details; this test must not depend on that.
    monkeypatch.setattr(
        "clinic_voice_receptionist.numbers.client.get_settings",
        lambda: type("Core", (), {"twilio_account_sid": "", "twilio_auth_token": ""})(),
    )
    app.state.twilio_numbers = None
    app.state.__dict__.pop("_twilio_numbers", None)
    t = await create_test_tenant()
    assert (await client.get("/inbound/numbers", headers=_h(t))).json()["enabled"] is False
    assert (await _buy(client, t, _random_number())).status_code == 409


async def test_the_webhook_is_only_set_when_the_public_address_is_configured(client, twilio, monkeypatch, num2, num):
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "")  # a developer's .env may have one; start from none
    get_voice_settings.cache_clear()
    t = await create_test_tenant()
    await _buy(client, t, num)
    assert twilio.calls[-1] == ("buy", num, None)
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "https://api.example.com/")
    get_voice_settings.cache_clear()
    try:
        await _buy(client, t, num2)
        assert twilio.calls[-1][2] == "https://api.example.com/features/voice_receptionist/twilio/voice"
    finally:
        monkeypatch.undo()
        get_voice_settings.cache_clear()


# ---- assigning and releasing -----------------------------------------------------------------------------


async def test_a_number_can_be_assigned_to_an_agent_and_unassigned(client, num):
    t = await create_test_tenant()
    agent = await _agent(client, t)
    number = (await _buy(client, t, num)).json()
    r = await client.put(f"/inbound/numbers/{number['id']}", json={"agent_id": agent["id"]}, headers=_h(t))
    assert r.status_code == 200 and r.json()["agent_id"] == agent["id"]
    r = await client.put(f"/inbound/numbers/{number['id']}", json={"agent_id": None}, headers=_h(t))
    assert r.json()["agent_id"] is None


async def test_a_number_cannot_go_to_a_missing_or_switched_off_agent(client, num2, num):
    t, other = await create_test_tenant(), await create_test_tenant()
    foreign = await _agent(client, other, "Theirs")
    off = await _agent(client, t, "Off agent", is_active=False)
    number = (await _buy(client, t, num)).json()
    for agent_id in (foreign["id"], off["id"], "00000000-0000-0000-0000-000000000009"):
        r = await client.put(f"/inbound/numbers/{number['id']}", json={"agent_id": agent_id}, headers=_h(t))
        assert r.status_code in (404, 409)
    bad_buy = await _buy(client, t, num2, agent_id=off["id"])
    assert bad_buy.status_code == 409


async def test_releasing_gives_the_number_back_to_twilio(client, twilio, num):
    t = await create_test_tenant()
    number = (await _buy(client, t, num)).json()
    assert (await client.delete(f"/inbound/numbers/{number['id']}", headers=_h(t))).status_code == 204
    assert twilio.owned == {}
    assert (await client.get("/inbound/numbers", headers=_h(t))).json()["numbers"] == []
    assert (await client.delete(f"/inbound/numbers/{number['id']}", headers=_h(t))).status_code == 404


async def test_the_real_client_sets_the_voice_url_with_post():
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), request.content.decode()
        return httpx.Response(200, json={})

    await _twilio(handler).set_voice_url("PN1", "https://x/y")
    assert seen["url"].endswith("/IncomingPhoneNumbers/PN1.json") and "VoiceMethod=POST" in seen["body"]
    with pytest.raises(TwilioError):
        await _twilio(lambda r: httpx.Response(400, json={"message": "no"})).set_voice_url("PN1", "https://x/y")


async def test_a_failed_release_keeps_the_number_listed(client, twilio, monkeypatch, num):
    t = await create_test_tenant()
    number = (await _buy(client, t, num)).json()

    async def broken(sid):
        raise TwilioError("Twilio could not release this number.", 502)

    monkeypatch.setattr(twilio, "release", broken)
    r = await client.delete(f"/inbound/numbers/{number['id']}", headers=_h(t))
    assert r.status_code == 502
    assert len((await client.get("/inbound/numbers", headers=_h(t))).json()["numbers"]) == 1


async def test_one_clinic_cannot_see_assign_or_release_anothers_numbers(client, twilio, num):
    a, b = await create_test_tenant(), await create_test_tenant()
    number = (await _buy(client, a, num)).json()
    assert (await client.get("/inbound/numbers", headers=_h(b))).json()["numbers"] == []
    assert (await client.put(f"/inbound/numbers/{number['id']}", json={}, headers=_h(b))).status_code == 404
    assert (await client.delete(f"/inbound/numbers/{number['id']}", headers=_h(b))).status_code == 404
    assert list(twilio.owned.values()) == [num]
    async with tenant_session(a) as s:
        assert len((await s.scalars(select(PhoneNumber))).all()) == 1


def test_numbers_are_classified_by_prefix():
    assert service.kind_of("+18885550100") == "toll_free" and service.kind_of("+12125550100") == "local"


# ---- the real Twilio client, against a recorded transport -----------------------------------------------------


def _twilio(handler):
    return TwilioNumbers("AC123", "secret-token", transport=httpx.MockTransport(handler))


async def test_search_asks_twilio_for_voice_numbers_in_the_area():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        return httpx.Response(
            200,
            json={
                "available_phone_numbers": [{"phone_number": "+12125550100", "locality": "New York", "region": "NY"}]
            },
        )

    found = await _twilio(handler).search(kind="local", area_code="212", contains=None)
    assert found[0].number == "+12125550100" and found[0].locality == "New York"
    assert "AvailablePhoneNumbers/US/Local.json" in seen["url"] and "AreaCode=212" in seen["url"]
    assert "VoiceEnabled=true" in seen["url"] and seen["auth"].startswith("Basic ")


async def test_buy_sends_the_number_and_webhook_once_and_never_retries():
    sent = []

    def handler(request):
        sent.append(request.content.decode())
        return httpx.Response(201, json={"sid": "PN1", "phone_number": "+12125550100"})

    bought = await _twilio(handler).buy(number="+12125550100", friendly_name="Avishkar abc", voice_url="https://x/y")
    assert bought.sid == "PN1" and len(sent) == 1
    assert "PhoneNumber=%2B12125550100" in sent[0] and "VoiceUrl=https%3A%2F%2Fx%2Fy" in sent[0]


async def test_errors_show_twilio_words_but_never_the_credentials():
    def handler(request):
        return httpx.Response(400, json={"message": "Phone number is not available", "code": 21452})

    with pytest.raises(TwilioError) as caught:
        await _twilio(handler).buy(number="+12125550100", friendly_name="x", voice_url=None)
    assert "not available" in str(caught.value) and "secret-token" not in str(caught.value)

    def refused(request):
        return httpx.Response(401, json={"message": "Authenticate"})

    with pytest.raises(TwilioError) as caught:
        await _twilio(refused).search(kind="local", area_code=None, contains=None)
    assert "did not accept" in str(caught.value) and "secret-token" not in json.dumps(str(caught.value))


async def test_an_unreachable_twilio_is_a_plain_message():
    def handler(request):
        raise httpx.ConnectError("boom")

    with pytest.raises(TwilioError) as caught:
        await _twilio(handler).search(kind="local", area_code=None, contains=None)
    assert caught.value.status == 503


async def test_releasing_a_number_twilio_no_longer_has_is_fine():
    await _twilio(lambda r: httpx.Response(404, json={})).release("PN1")
    with pytest.raises(TwilioError):
        await _twilio(lambda r: httpx.Response(500, json={})).release("PN1")


async def test_a_403_shows_twilios_own_reason_not_a_wrong_credentials_message():
    def refused(request):
        return httpx.Response(403, json={"message": "Account needs a compliance profile to buy numbers", "code": 20003})

    with pytest.raises(TwilioError) as caught:
        await _twilio(refused).buy(number="+12125550100", friendly_name="x", voice_url=None)
    assert "compliance profile" in str(caught.value) and "account details" not in str(caught.value)

    with pytest.raises(TwilioError) as caught:  # a 403 with no explanation still points at approval, not credentials
        await _twilio(lambda r: httpx.Response(403, json={})).buy(
            number="+12125550100", friendly_name="x", voice_url=None
        )
    assert "approval" in str(caught.value)


async def test_saving_routing_points_the_number_at_our_call_address_when_it_is_configured(
    client, twilio, num, monkeypatch
):
    t = await create_test_tenant()
    agent = await _agent(client, t)
    number = (await _buy(client, t, num)).json()
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "https://api.example.com")
    get_voice_settings.cache_clear()
    try:
        r = await client.put(f"/inbound/numbers/{number['id']}", json={"agent_id": agent["id"]}, headers=_h(t))
        assert r.status_code == 200 and r.json()["agent_id"] == agent["id"]
        sid = next(iter(twilio.owned))
        assert twilio.calls[-1] == (
            "set_voice_url",
            sid,
            "https://api.example.com/features/voice_receptionist/twilio/voice",
        )
        twilio.fail_next_buy = "Twilio refused the change."
        refused = await client.put(f"/inbound/numbers/{number['id']}", json={"agent_id": None}, headers=_h(t))
        assert refused.status_code == 409 and "refused" in refused.json()["detail"]
        listing = (await client.get("/inbound/numbers", headers=_h(t))).json()["numbers"]
        assert listing[0]["agent_id"] == agent["id"]  # a refused change leaves the routing as it was
    finally:
        monkeypatch.undo()
        get_voice_settings.cache_clear()


async def test_saving_routing_without_a_call_address_does_not_touch_twilio(client, twilio, num, monkeypatch):
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "")
    get_voice_settings.cache_clear()
    try:
        t = await create_test_tenant()
        agent = await _agent(client, t)
        number = (await _buy(client, t, num)).json()
        await client.put(f"/inbound/numbers/{number['id']}", json={"agent_id": agent["id"]}, headers=_h(t))
        assert all(call[0] != "set_voice_url" for call in twilio.calls)
    finally:
        monkeypatch.undo()
        get_voice_settings.cache_clear()
