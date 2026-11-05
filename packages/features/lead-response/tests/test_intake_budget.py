"""The 300 ms goal: the text is saved before the answer, and the work before the answer stays small.

These tests count the SQL statements (round trips) the route runs, so a change that adds a query shows up here. The
measured numbers are the ceilings. The route never calls a provider: that would not fit the budget."""

import pytest
from lr_intake import Counter, Intake, rows, sid, twilio_pairs

from clinic_db.models.lead_response import Job, Message
from clinic_lead_response.gateway import service as gateway_service

# set_config, feature check, contact lookup, conversation upsert, message insert, first-inbound consent, flood count,
# ack job.
KNOWN_LEAD = 8
# A new lead adds: savepoint, contact insert, identity insert, release savepoint.
NEW_LEAD = 12
# set_config, feature check, contact lookup, conversation upsert, message insert (which found the copy).
DUPLICATE = 5


@pytest.fixture
def intake(monkeypatch):
    # The route has no provider. If any code under it tried to send, this would fail the test.
    async def no_send(self, *args, **kwargs):
        raise AssertionError("intake must not send a message before it answers")

    monkeypatch.setattr(gateway_service.Gateway, "send", no_send)
    return Intake(monkeypatch)


async def test_a_text_from_a_new_lead_costs_few_statements(intake, make_tenant):
    tenant = await make_tenant()
    with Counter() as statements:
        response = await intake.post(tenant)
    print(f"\nnew lead: {len(statements)} statements")
    assert response.status_code == 200
    assert len(statements) <= NEW_LEAD


async def test_a_text_from_a_known_lead_costs_fewer(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    with Counter() as statements:
        response = await intake.post(tenant, twilio_pairs(MessageSid=sid(2)))
    print(f"\nknown lead: {len(statements)} statements")
    assert response.status_code == 200
    assert len(statements) <= KNOWN_LEAD


async def test_a_repeated_delivery_stops_early(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant)
    with Counter() as statements:
        response = await intake.post(tenant)
    print(f"\nduplicate: {len(statements)} statements")
    assert response.status_code == 200
    assert len(statements) <= DUPLICATE


async def test_a_refused_request_costs_no_statements(intake, make_tenant):
    tenant = await make_tenant()
    with Counter() as statements:
        await intake.post(tenant, sign=False)
        await intake.post(tenant, channel="mms")
        await intake.post(tenant, twilio_pairs(MessageSid="nope"))
    assert statements == []


async def test_the_text_is_committed_before_the_answer_arrives(intake, make_tenant):
    """The answer is only sent after the transaction commits: a read from another connection sees the row."""
    tenant = await make_tenant()
    response = await intake.post(tenant)
    assert response.status_code == 200
    assert len(await rows(tenant, Message)) == 1 and len(await rows(tenant, Job)) == 1
