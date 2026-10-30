"""The ack has a 5 second end-to-end goal, so the work before the provider call must stay small. These tests count the
SQL statements (round trips) the gateway runs, so a change that adds a query shows up here."""

from contextlib import contextmanager

from lr_gateway import FakeProvider, gateway, make_lead, request
from sqlalchemy import event
from sqlalchemy.engine import Engine

from clinic_lead_response.gateway.types import Lane, Outcome, Purpose

# Measured: set_config, already-sent check, conversation + phone, tenant, settings, consent, 2 inserts.
BEFORE_THE_CALL = 8
# After the call: set_config, the sent event, the conversation's last_outbound_at.
WHOLE_SEND = 11


@contextmanager
def counting():
    statements: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", listener)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", listener)


async def test_an_ack_costs_few_statements_before_the_provider_is_called(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    seen = {}

    with counting() as statements:

        async def hook(request_):
            seen["before"] = len(statements)

        result = await gateway(FakeProvider(hook=hook)).send(t, request(lead))
    print(f"\nack: {seen['before']} statements before the provider call, {len(statements)} in all")
    assert result.outcome is Outcome.SENT
    assert seen["before"] <= BEFORE_THE_CALL
    assert len(statements) <= WHOLE_SEND


async def test_a_repeated_send_is_cheap(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    g = gateway(FakeProvider())
    req = request(lead)
    await g.send(t, req)
    with counting() as statements:
        again = await g.send(t, req)
    print(f"\nduplicate: {len(statements)} statements")
    assert again.outcome is Outcome.DUPLICATE and len(statements) <= 4


async def test_a_blocked_send_costs_no_more_than_a_sent_one(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(False, "stop"))
    with counting() as statements:
        result = await gateway(FakeProvider()).send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    print(f"\nblocked: {len(statements)} statements")
    assert result.outcome is Outcome.BLOCKED and len(statements) <= BEFORE_THE_CALL
