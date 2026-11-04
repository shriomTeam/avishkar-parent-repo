"""What the reply and task API (a later chunk) must do for the engine to see it. See ``engine/contract.py``."""

import uuid
from datetime import timedelta

from lr_engine import jobs_of_kind, messages_of, tasks_of
from lr_gateway import make_lead
from lr_wait import go_to, holdings, open_wait, set_task

from clinic_lead_response.engine import contract
from clinic_lead_response.gateway.types import SENDER_KIND, Lane, Purpose, SendRequest


def test_the_contract_names_are_the_ones_the_gateway_and_the_schema_use():
    assert contract.STAFF_SENDER_KIND == SENDER_KIND[Purpose.STAFF_REPLY] == "staff"
    assert contract.TASK_OPEN == "open" and contract.TASK_HANDLED == "handled"


def test_the_cancel_reasons_fit_the_column_and_are_fixed_words():
    for reason in (
        contract.CANCEL_STAFF_REPLY,
        contract.CANCEL_HANDLED,
        contract.CANCEL_TASK_CLOSED,
        contract.CANCEL_STOP,
    ):
        assert reason.isidentifier() and len(reason) <= 32


async def test_a_reply_sent_through_the_gateway_as_a_staff_reply_stands_the_timers_down(make_tenant):
    """The whole contract in one go: send as staff through Gateway.send, and the engine sees an answer."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    wait.clock.advance(minutes=3)
    sent = await wait.engine.gateway.send(
        tenant,
        SendRequest(
            lead.conversation,
            Purpose.STAFF_REPLY,
            "Hi, this is a person.",
            Lane.LIVE,
            f"staff:{uuid.uuid4()}",
            uuid.uuid4(),
        ),
    )
    (reply,) = [m for m in await messages_of(tenant) if m.id == sent.message_id]
    assert (reply.direction, reply.sender_kind) == ("outbound", "staff")
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert {
        j.cancel_reason for j in await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    } == {"staff_reply"}


async def test_marking_a_task_handled_is_just_the_status_and_the_time(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await set_task(tenant, status=contract.TASK_HANDLED, handled_at=wait.clock())
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert holdings(wait.provider) == []
    assert {j.cancel_reason for j in await jobs_of_kind(tenant, "holding")} == {"handled"}


async def test_the_reply_api_may_note_the_time_itself_and_the_engine_leaves_it(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    stamped = wait.task.received_at + timedelta(minutes=2)
    await set_task(tenant, first_staff_reply_at=stamped)
    wait.clock.advance(minutes=3)
    await wait.engine.gateway.send(
        tenant,
        SendRequest(lead.conversation, Purpose.STAFF_REPLY, "On it.", Lane.LIVE, f"staff:{uuid.uuid4()}", uuid.uuid4()),
    )
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert (await tasks_of(tenant))[0].first_staff_reply_at == stamped


async def test_a_message_that_only_looks_like_a_reply_is_not_one(make_tenant):
    """An ack or a holding message is outbound too, but it is ours, not a person's."""
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)  # the ack is an outbound message in the conversation
    assert any(m.direction == "outbound" and m.sender_kind == "ack" for m in await messages_of(tenant))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1
