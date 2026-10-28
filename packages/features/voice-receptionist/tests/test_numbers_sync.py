import json
import random
import uuid

import httpx
import pytest

from clinic_core.database import tenant_session
from clinic_core.settings import get_settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.voice import PhoneNumber
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.numbers import sync
from clinic_voice_receptionist.numbers.twilio import TwilioError, TwilioNumbers
from clinic_voice_receptionist.testing import FakeNumbers

URL = "https://api.example.com/features/voice_receptionist/twilio/voice"


def _number():
    area = f"{random.randint(2, 9)}{random.randint(0, 99):02d}"
    exchange = f"{random.randint(2, 9)}{random.randint(0, 99):02d}"
    return f"+1{area}{exchange}{random.randint(0, 9999):04d}"


async def _own(fake, current_url):
    """A number this server owns (a row), and what Twilio currently has for it."""
    tenant, sid = await create_test_tenant(), "PN" + uuid.uuid4().hex
    async with tenant_session(tenant) as s:
        s.add(PhoneNumber(tenant_id=tenant, number=_number(), provider_sid=sid, kind="local"))
    fake.urls[sid] = current_url
    return sid


async def test_numbers_pointing_elsewhere_are_repointed_and_matching_ones_are_left_alone():
    fake = FakeNumbers()
    stale = await _own(fake, "https://old.ngrok-free.dev/features/voice_receptionist/twilio/voice")
    unset = await _own(fake, "")
    current = await _own(fake, URL)
    changed = await sync.sync_voice_urls(fake, URL, get_settings().database_system_url)
    assert changed >= 2  # other rows in a shared development database may be changed too
    assert fake.urls[stale] == URL and fake.urls[unset] == URL and fake.urls[current] == URL
    touched = {c[1] for c in fake.calls if c[0] == "set_voice_url"}
    assert current not in touched  # already right: no call


async def test_numbers_on_the_account_that_this_server_does_not_own_are_never_touched():
    fake = FakeNumbers()
    fake.urls["PN" + uuid.uuid4().hex] = "https://someone-elses-app.example/voice"
    foreign = next(iter(fake.urls))
    await sync.sync_voice_urls(fake, URL, get_settings().database_system_url)
    assert fake.urls[foreign] == "https://someone-elses-app.example/voice"


async def test_a_number_twilio_no_longer_has_is_skipped():
    fake = FakeNumbers()
    gone = await _own(fake, "x")
    del fake.urls[gone]
    await sync.sync_voice_urls(fake, URL, get_settings().database_system_url)
    assert all(c[1] != gone for c in fake.calls if c[0] == "set_voice_url")


class App:
    def __init__(self, fake):
        from types import SimpleNamespace

        self.state = SimpleNamespace(twilio_numbers=fake, settings=get_settings())


@pytest.fixture
def address(monkeypatch):
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "https://api.example.com")
    get_voice_settings.cache_clear()
    yield
    get_voice_settings.cache_clear()


async def test_startup_syncs_when_twilio_and_the_address_are_configured(address):
    fake = FakeNumbers()
    sid = await _own(fake, "https://old.example/voice")
    await sync.sync_on_startup(App(fake))
    assert fake.urls[sid] == URL


async def test_startup_does_nothing_without_an_address_or_without_twilio(monkeypatch):
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "")
    get_voice_settings.cache_clear()
    fake = FakeNumbers()
    await _own(fake, "https://old.example/voice")
    await sync.sync_on_startup(App(fake))
    assert fake.calls == []  # no address: Twilio is not even asked
    monkeypatch.setenv("VOICE_PUBLIC_API_URL", "https://api.example.com")
    get_voice_settings.cache_clear()
    app = App(None)
    app.state.twilio_numbers = None
    monkeypatch.setattr(
        "clinic_voice_receptionist.numbers.client.get_settings",
        lambda: type("Core", (), {"twilio_account_sid": "", "twilio_auth_token": ""})(),
    )
    await sync.sync_on_startup(app)  # no Twilio account details: nothing to do
    get_voice_settings.cache_clear()


async def test_a_twilio_failure_surfaces_to_the_startup_runner_which_ignores_it(address):
    fake = FakeNumbers()
    await _own(fake, "x")

    async def broken():
        raise TwilioError("Twilio could not be reached.", 503)

    fake.list_voice_urls = broken
    with pytest.raises(TwilioError):  # the API's startup runner catches and logs this; see test_startup_hooks
        await sync.sync_on_startup(App(fake))


# ---- the real client's listing ---------------------------------------------------------------------------------


async def test_listing_reads_every_page_of_the_account_numbers():
    pages = {
        "IncomingPhoneNumbers.json": {
            "incoming_phone_numbers": [{"sid": "PN1", "voice_url": "https://a"}, {"sid": "PN2", "voice_url": None}],
            "next_page_uri": "/2010-04-01/Accounts/AC1/IncomingPhoneNumbers.json?Page=1&PageSize=1000",
        },
        "page2": {"incoming_phone_numbers": [{"sid": "PN3", "voice_url": "https://c"}], "next_page_uri": None},
    }
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=pages["page2" if "Page=1" in str(request.url) else "IncomingPhoneNumbers.json"])

    urls = await TwilioNumbers("AC1", "t", transport=httpx.MockTransport(handler)).list_voice_urls()
    assert urls == {"PN1": "https://a", "PN2": "", "PN3": "https://c"} and len(seen) == 2


async def test_a_listing_refused_by_twilio_is_an_error_not_an_empty_answer():
    client = TwilioNumbers("AC1", "t", transport=httpx.MockTransport(lambda r: httpx.Response(500, json={})))
    with pytest.raises(TwilioError):
        await client.list_voice_urls()
    assert json.dumps({}) == "{}"
