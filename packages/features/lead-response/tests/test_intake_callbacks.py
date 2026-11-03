"""The address the gateway gives Twilio for delivery receipts."""

import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from lr_gateway import FakeProvider, accepted, event_pairs, gateway, make_lead, request
from lr_intake import PUBLIC, Intake, receipt_pairs, sid

from clinic_lead_response.config import IntakeSettings
from clinic_lead_response.feature import feature
from clinic_lead_response.intake import callbacks

TENANT = uuid.UUID("11111111-2222-3333-4444-555555555555")
MESSAGE = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def configure(monkeypatch, value: str) -> None:
    monkeypatch.setattr(callbacks, "get_intake_settings", lambda: IntakeSettings(_env_file=None, public_api_url=value))


def test_nothing_is_returned_while_the_public_address_is_not_set(monkeypatch):
    configure(monkeypatch, "")
    assert callbacks.status_callback_url(TENANT, MESSAGE) is None


@pytest.mark.parametrize("bad", ["   ", "api.example.test", "https://api.example.test/features", "ftp://x.test"])
def test_a_bad_public_address_gives_nothing_not_a_broken_address(monkeypatch, bad):
    configure(monkeypatch, bad)
    assert callbacks.status_callback_url(TENANT, MESSAGE) is None


def test_the_address_is_the_receipt_route_with_the_message_id(monkeypatch):
    configure(monkeypatch, PUBLIC)
    assert callbacks.status_callback_url(TENANT, MESSAGE) == (
        f"{PUBLIC}/features/lead_response/status/sms/{TENANT}?m={MESSAGE}"
    )


@pytest.mark.parametrize("written", [PUBLIC, PUBLIC + "/", f"  {PUBLIC}  "])
def test_a_trailing_slash_or_spaces_in_the_setting_do_not_change_the_address(monkeypatch, written):
    configure(monkeypatch, written)
    assert callbacks.status_callback_url(TENANT, MESSAGE).startswith(f"{PUBLIC}/features/")


def test_the_address_holds_only_ids(monkeypatch):
    configure(monkeypatch, PUBLIC)
    url = callbacks.status_callback_url(TENANT, MESSAGE)
    assert urlsplit(url).query == f"m={MESSAGE}"
    assert re.fullmatch(
        rf"{re.escape(PUBLIC)}/features/lead_response/status/sms/[0-9a-f-]{{36}}\?m=[0-9a-f-]{{36}}", url
    )


def test_the_path_matches_the_route_the_feature_registers(monkeypatch):
    configure(monkeypatch, PUBLIC)
    registered = {route.path for route in feature.websocket_router.routes}
    assert "/status/{channel}/{tenant}" in registered
    expected = callbacks.MOUNT + "/status/{channel}/{tenant}".format(channel="sms", tenant=TENANT)
    assert urlsplit(callbacks.status_callback_url(TENANT, MESSAGE)).path == expected


def test_the_mount_is_where_the_platform_mounts_every_feature():
    assert callbacks.MOUNT == f"/features/{feature.key}"


async def test_the_gateway_hands_the_address_to_the_provider_on_every_send(monkeypatch, make_tenant):
    configure(monkeypatch, PUBLIC)
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(accepted(sid(7)))
    result = await gateway(provider, status_callback=callbacks.status_callback_url).send(tenant, request(lead))
    (sent,) = provider.requests
    assert sent.status_callback_url == callbacks.status_callback_url(tenant, result.message_id)


async def test_with_no_public_address_the_provider_is_told_no_callback(monkeypatch, make_tenant):
    configure(monkeypatch, "")
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    provider = FakeProvider(accepted(sid(7)))
    await gateway(provider, status_callback=callbacks.status_callback_url).send(tenant, request(lead))
    assert provider.requests[0].status_callback_url is None


async def test_the_address_the_gateway_gave_works_when_twilio_calls_it_back(monkeypatch, make_tenant):
    """The whole loop: send, take the address handed to Twilio, call it the way Twilio does, and see the status."""
    tenant = await make_tenant()
    intake = Intake(monkeypatch)  # replaces the settings the route reads
    configure(monkeypatch, PUBLIC)
    lead = await make_lead(tenant)
    provider = FakeProvider(accepted(sid(7)))
    result = await gateway(provider, status_callback=callbacks.status_callback_url).send(tenant, request(lead))
    url = urlsplit(provider.requests[0].status_callback_url)
    assert url.path == f"/features/lead_response/status/sms/{tenant}"
    message_id = parse_qs(url.query)["m"][0]
    assert message_id == str(result.message_id)

    response = await intake.post_status(tenant, receipt_pairs(sid(7), "delivered"), m=message_id)
    assert response.status_code == 200
    assert sorted(s for _, s in await event_pairs(tenant, result.message_id)) == ["delivered", "sending", "sent"]
