"""The keyword path costs a second transaction, so it is counted on its own. A keyword text is rare, but the answer
still waits for it, so a change that adds a query shows up here. The measured numbers are the ceilings."""

import pytest
from lr_intake import Counter, Intake, sid, twilio_pairs

from clinic_lead_response.gateway import service as gateway_service

# First transaction for a new lead's STOP: set_config, feature check, contact lookup, savepoint, contact, identity,
# release, conversation upsert, message insert (9). Second transaction: set_config, contact check, consent lookup,
# consent insert, audit insert (5).
STOP_NEW_LEAD = 14
# A known lead has no savepoint, contact or identity insert: 5 + 5.
STOP_OR_START_KNOWN_LEAD = 10
# HELP: 8 in the first transaction (it also writes the first-inbound grant, counts and queues the help job), then
# set_config, contact check, consent lookup, clinic name (4).
HELP_KNOWN_LEAD = 12
# A retry of a STOP that already took effect: the first five, the stored message's id, and the "already applied" check.
STOP_RETRY_APPLIED = 7


@pytest.fixture
def intake(monkeypatch):
    async def no_send(self, *args, **kwargs):
        raise AssertionError("intake must not send a message, not even for STOP, START or HELP")

    monkeypatch.setattr(gateway_service.Gateway, "send", no_send)
    return Intake(monkeypatch)


async def measure(intake, tenant, n, body):
    with Counter() as statements:
        response = await intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=body))
    print(f"\n{body} (sid {n}): {len(statements)} statements")
    assert response.status_code == 200
    return len(statements)


async def test_stop_from_a_new_lead(intake, make_tenant):
    tenant = await make_tenant()
    assert await measure(intake, tenant, 1, "STOP") <= STOP_NEW_LEAD


async def test_start_from_a_known_lead(intake, make_tenant):
    tenant = await make_tenant()
    await measure(intake, tenant, 1, "hello")
    assert await measure(intake, tenant, 2, "START") <= STOP_OR_START_KNOWN_LEAD


async def test_stop_from_a_known_lead(intake, make_tenant):
    tenant = await make_tenant()
    await measure(intake, tenant, 1, "hello")
    assert await measure(intake, tenant, 2, "STOP") <= STOP_OR_START_KNOWN_LEAD


async def test_help_from_a_known_lead(intake, make_tenant):
    tenant = await make_tenant()
    await measure(intake, tenant, 1, "START")
    assert await measure(intake, tenant, 2, "HELP") <= HELP_KNOWN_LEAD


async def test_a_retried_stop_that_already_took_effect_stops_early(intake, make_tenant):
    tenant = await make_tenant()
    await measure(intake, tenant, 1, "STOP")
    assert await measure(intake, tenant, 1, "STOP") <= STOP_RETRY_APPLIED


async def test_an_ordinary_text_still_costs_what_it_did(intake, make_tenant):
    """Telling keywords apart adds no statement to an ordinary text (8 for a known lead, as before)."""
    tenant = await make_tenant()
    await measure(intake, tenant, 1, "hello")
    assert await measure(intake, tenant, 2, "hello again") <= 8
