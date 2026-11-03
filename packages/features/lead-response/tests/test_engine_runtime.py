"""The one gateway the app shares, and its link to the delivery-receipt address."""

from lr_engine import make_engine, messages_of, seed_text
from lr_gateway import FakeProvider, accepted, make_lead
from lr_intake import PUBLIC

from clinic_lead_response import runtime
from clinic_lead_response.config import IntakeSettings
from clinic_lead_response.intake import callbacks, routes


def test_the_shared_gateway_is_built_once(monkeypatch):
    built = []
    monkeypatch.setattr(runtime, "build_gateway", lambda **kw: built.append(kw) or object())
    runtime.get_gateway.cache_clear()
    try:
        first, second = runtime.get_gateway(), runtime.get_gateway()
        assert first is second and len(built) == 1
    finally:
        runtime.get_gateway.cache_clear()


def test_it_is_built_with_the_receipt_address_wired_in(monkeypatch):
    built = []
    monkeypatch.setattr(runtime, "build_gateway", lambda **kw: built.append(kw) or object())
    runtime.get_gateway.cache_clear()
    try:
        runtime.get_gateway()
        assert built == [{"status_callback": callbacks.status_callback_url}]
    finally:
        runtime.get_gateway.cache_clear()


def test_the_real_gateway_carries_the_callback_builder():
    runtime.get_gateway.cache_clear()
    try:
        assert runtime.get_gateway()._status_callback is callbacks.status_callback_url
    finally:
        runtime.get_gateway.cache_clear()


def test_the_intake_routes_use_the_same_gateway():
    assert routes.get_gateway is runtime.get_gateway


async def test_every_send_carries_the_receipt_address_when_the_public_address_is_set(make_tenant, monkeypatch):
    monkeypatch.setattr(callbacks, "get_intake_settings", lambda: IntakeSettings(_env_file=None, public_api_url=PUBLIC))
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine(FakeProvider(accepted("SM" + "1" * 32)))
    engine.gateway._status_callback = callbacks.status_callback_url  # what runtime.get_gateway wires in
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    (message,) = [m for m in await messages_of(tenant) if m.direction == "outbound"]
    assert provider.requests[0].status_callback_url == callbacks.status_callback_url(tenant, message.id)
    assert f"/status/sms/{tenant}?m={message.id}" in provider.requests[0].status_callback_url


async def test_without_a_public_address_no_callback_is_sent(make_tenant, monkeypatch):
    monkeypatch.setattr(callbacks, "get_intake_settings", lambda: IntakeSettings(_env_file=None, public_api_url=""))
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await seed_text(tenant, lead)
    engine, provider, clock = make_engine(FakeProvider(accepted("SM" + "1" * 32)))
    engine.gateway._status_callback = callbacks.status_callback_url
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    assert provider.requests[0].status_callback_url is None
