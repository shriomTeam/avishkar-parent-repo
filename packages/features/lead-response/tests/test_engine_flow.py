"""From a signed inbound text, through the real intake route, to the engine's ack: what intake writes is what the engine
reads."""

import pytest
from lr_engine import jobs_of_kind, make_engine, messages_of, tasks_of
from lr_intake import LEAD_NUMBER, OUR_NUMBER, Intake, sid, twilio_pairs

from clinic_core.database import system_session
from clinic_core.entitlements import set_feature
from clinic_db.models.lead_response import DEFAULT_ACK_TEXT


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def text(intake, tenant, body, n=1):
    response = await intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=body))
    assert response.status_code == 200


def engine_after_the_texts():
    engine, provider, clock = make_engine()
    clock.advance(seconds=2)  # the route stamped its jobs a moment ago
    return engine, provider


async def test_a_text_through_the_route_gets_a_task_and_an_ack(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "Hi, do you do botox?")
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 1
    (sent,) = provider.requests
    assert (sent.to, sent.from_number, sent.body) == (LEAD_NUMBER, OUR_NUMBER, DEFAULT_ACK_TEXT)
    messages = await messages_of(tenant)
    assert [(m.direction, m.sender_kind) for m in messages] == [("inbound", "contact"), ("outbound", "ack")]
    (task,) = await tasks_of(tenant)
    assert task.first_ack_at is not None and task.trace_id == messages[0].trace_id == messages[1].trace_id
    assert (await jobs_of_kind(tenant, "ack"))[0].status == "done"
    assert len(await jobs_of_kind(tenant, "holding")) == 1 and len(await jobs_of_kind(tenant, "escalate")) == 1


async def test_the_same_text_delivered_twice_is_acked_once(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "Hello", n=1)
    await text(intake, tenant, "Hello", n=1)
    engine, provider = engine_after_the_texts()
    await engine.run_due(tenant)
    assert len(provider.requests) == 1 and len(await jobs_of_kind(tenant, "ack")) == 1


async def test_several_texts_in_a_row_are_one_wait_and_one_ack(intake, make_tenant):
    tenant = await make_tenant()
    for n in range(1, 6):
        await text(intake, tenant, f"message number {n}", n=n)
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 5
    assert len(provider.requests) == 1 and len(await tasks_of(tenant)) == 1
    codes = sorted(str(j.last_error_code) for j in await jobs_of_kind(tenant, "ack"))
    assert codes == ["None"] + ["already_acked"] * 4


async def test_a_flood_of_texts_is_one_task_and_one_ack(intake, make_tenant):
    tenant = await make_tenant()
    for n in range(1, 31):
        await text(intake, tenant, "again", n=n)
    engine, provider = engine_after_the_texts()
    while await engine.run_due(tenant, limit=10):
        pass
    assert len(provider.requests) == 1 and len(await tasks_of(tenant)) == 1


async def test_stop_creates_no_job_so_the_engine_has_nothing_to_do(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "STOP")
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 0
    assert provider.requests == [] and await tasks_of(tenant) == []


async def test_a_text_after_stop_still_gets_a_task_but_no_message(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "STOP", n=1)
    await text(intake, tenant, "Actually, can someone call me?", n=2)
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 1
    assert provider.requests == []
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.first_ack_at is None
    assert (await jobs_of_kind(tenant, "ack"))[0].last_error_code == "blocked_opted_out"
    assert len(await jobs_of_kind(tenant, "holding")) == 1 and len(await jobs_of_kind(tenant, "escalate")) == 1


async def test_start_creates_no_job(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "START")
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 0 and provider.requests == []


async def test_help_creates_a_job_the_engine_cancels_without_sending(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "HELP")
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 1
    assert provider.requests == [] and await tasks_of(tenant) == []
    (help_job,) = await jobs_of_kind(tenant, "help")
    assert (help_job.status, help_job.cancel_reason) == ("cancelled", "help_wording_pending")


async def test_two_clinics_with_the_same_lead_number_are_answered_separately(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await text(intake, a, "hello a", n=1)
    await text(intake, b, "hello b", n=1)
    engine, provider = engine_after_the_texts()
    await engine.run_due(a)
    await engine.run_due(b)
    assert len(provider.requests) == 2 and len(await tasks_of(a)) == 1 and len(await tasks_of(b)) == 1
    assert {m.conversation_id for m in await messages_of(a)}.isdisjoint(
        {m.conversation_id for m in await messages_of(b)}
    )


async def test_a_clinic_without_the_feature_gets_no_task_even_if_a_job_exists(intake, make_tenant):
    tenant = await make_tenant()
    await text(intake, tenant, "hello")
    async with system_session() as session:
        await set_feature(session, tenant, "lead_response", enabled=False)
    engine, provider = engine_after_the_texts()
    assert await engine.run_due(tenant) == 0 and provider.requests == [] and await tasks_of(tenant) == []
