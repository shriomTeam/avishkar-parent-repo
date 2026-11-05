"""The whole default flow with the engine switched on: a text in, the ack, the task, the holding message after the
timer, the escalation after the target, and the variants that stand the timers down. Real signed texts through
the real route, the fast path, and the tick; a fake clock and a fake provider."""

from datetime import timedelta

import pytest
from lr_engine import jobs_of_kind, messages_of, seed_text, tasks_of
from lr_gateway import Lead, audit_rows, make_lead
from lr_host import make_host
from lr_intake import Intake, sid, twilio_pairs
from lr_wait import opt_out, set_task, staff_reply

from clinic_db.models.lead_response import DEFAULT_ACK_TEXT
from clinic_lead_response.engine.holding import HOLDING_TEXT_PLACEHOLDER

ACTION = "lead_response.task.escalated"


async def say(intake, tenant, body, n):
    response = await intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=body))
    assert response.status_code == 200


async def start(monkeypatch, make_tenant, **kw):
    host = make_host(**kw)
    tenant = await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    return host, tenant, intake


def at(host, task, minutes):
    host.clock.now = task.received_at + timedelta(minutes=minutes, seconds=1)


async def make_lead_of(tenant):
    """The contact and conversation the route made for the first text, in the shape the helpers want."""
    (task,) = [t for t in await tasks_of(tenant)][:1]
    return Lead(tenant, task.contact_id, task.conversation_id)


async def kinds(tenant):
    return [m.sender_kind for m in await messages_of(tenant)]


async def test_the_default_flow_from_the_first_text_to_the_escalation(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "Hi, do you do botox?", 1)
    await host.fast.drain()  # the ack goes out in the background, within the request cycle
    (task,) = await tasks_of(tenant)
    assert task.first_ack_at is not None and await kinds(tenant) == ["contact", "ack"]
    assert [r.body for r in host.provider.requests] == [DEFAULT_ACK_TEXT]

    at(host, task, 14)
    assert (await host.scheduler.tick(tenant)).jobs_run == 0  # nothing yet
    at(host, task, 15)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1  # the holding message
    assert await kinds(tenant) == ["contact", "ack", "holding"]
    assert [r.body for r in host.provider.requests] == [DEFAULT_ACK_TEXT, HOLDING_TEXT_PLACEHOLDER]

    at(host, task, 29)
    assert (await host.scheduler.tick(tenant)).jobs_run == 0
    at(host, task, 30)
    assert (await host.scheduler.tick(tenant)).jobs_run == 1  # the escalation
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.escalation_state == "escalated" and task.holding_sent_at is not None
    assert len(await audit_rows(tenant, ACTION)) == 1
    assert len(host.provider.requests) == 2  # the escalation sent nobody anything
    assert {j.status for j in await jobs_of_kind(tenant, "ack") + await jobs_of_kind(tenant, "holding")} == {"done"}
    at(host, task, 120)
    assert (await host.scheduler.tick(tenant)).jobs_run == 0  # and nothing more happens


async def test_a_staff_reply_before_the_timer_stands_everything_down(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    lead = await make_lead(tenant)
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    (task,) = await tasks_of(tenant)
    at(host, task, 5)
    await staff_reply(tenant, lead, host.clock())
    at(host, task, 31)
    await host.scheduler.tick(tenant)
    assert await kinds(tenant) == ["contact", "ack", "staff"]  # no holding message
    (task,) = await tasks_of(tenant)
    assert task.escalation_state == "none" and task.first_staff_reply_at is not None and task.status == "open"
    jobs = await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    assert {(j.status, j.cancel_reason) for j in jobs} == {("cancelled", "staff_reply")}
    assert await audit_rows(tenant, ACTION) == []


async def test_a_stop_from_the_lead_stands_the_automatic_messages_down_and_keeps_the_task_open(
    monkeypatch, make_tenant
):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    (task,) = await tasks_of(tenant)
    at(host, task, 5)
    await say(intake, tenant, "STOP", 2)  # the route records the opt-out
    at(host, task, 31)
    await host.scheduler.tick(tenant)
    assert await kinds(tenant) == ["contact", "ack", "contact"]  # no holding message
    (task,) = await tasks_of(tenant)
    assert task.status == "open" and task.escalation_state == "none"
    jobs = await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    assert {(j.status, j.cancel_reason) for j in jobs} == {("cancelled", "stop")}


async def test_a_handled_task_stands_everything_down(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    (task,) = await tasks_of(tenant)
    await set_task(tenant, status="handled", handled_at=host.clock())
    at(host, task, 31)
    await host.scheduler.tick(tenant)
    assert await kinds(tenant) == ["contact", "ack"] and (await tasks_of(tenant))[0].escalation_state == "none"
    jobs = await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    assert {j.cancel_reason for j in jobs} == {"handled"}


async def test_more_texts_during_the_wait_change_neither_the_ack_nor_the_timers(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    (task,) = await tasks_of(tenant)
    at(host, task, 8)
    await say(intake, tenant, "Is anyone there?", 2)
    await host.fast.drain()
    await host.scheduler.tick(tenant)
    assert len([r for r in host.provider.requests if r.body == DEFAULT_ACK_TEXT]) == 1  # one ack per wait
    at(host, task, 15)
    await host.scheduler.tick(tenant)  # 15 minutes after the FIRST text
    assert await kinds(tenant) == ["contact", "ack", "contact", "holding"]
    at(host, task, 30)
    await host.scheduler.tick(tenant)
    assert (await tasks_of(tenant))[0].escalation_state == "escalated" and len(await tasks_of(tenant)) == 1


async def test_a_help_text_gets_nothing_and_makes_no_task(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "HELP", 1)
    await host.fast.drain()
    host.clock.advance(minutes=1)
    await host.scheduler.tick(tenant)
    assert host.provider.requests == [] and await tasks_of(tenant) == []
    assert {(j.status, j.cancel_reason) for j in await jobs_of_kind(tenant, "help")} == {
        ("cancelled", "help_wording_pending")
    }


async def test_a_lead_who_opted_out_before_still_gets_a_task_and_a_manager_flag_but_no_text(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    lead = await make_lead(tenant)
    await opt_out(tenant, lead)
    await say(intake, tenant, "Please call me back", 1)
    await host.fast.drain()
    (task,) = await tasks_of(tenant)
    assert host.provider.requests == [] and task.status == "open"
    at(host, task, 31)
    await host.scheduler.tick(tenant)
    jobs = await jobs_of_kind(tenant, "holding") + await jobs_of_kind(tenant, "escalate")
    assert {j.cancel_reason for j in jobs} == {"stop"} and host.provider.requests == []


async def test_a_wait_that_ends_and_a_new_text_start_a_new_wait_with_its_own_ack(monkeypatch, make_tenant):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    (first,) = await tasks_of(tenant)
    await set_task(tenant, status="handled", handled_at=host.clock())
    host.clock.advance(hours=2)
    # Two hours later. (Through the route the text would carry today's real time, a few milliseconds after the first
    # ack, which the engine rightly treats as a machine answering; so it is seeded two fake hours on, and the tick
    # answers it.)
    lead = await make_lead_of(tenant)
    await seed_text(tenant, lead, n=2, created_at=host.clock(), run_at=host.clock())
    host.clock.advance(seconds=1)
    await host.scheduler.tick(tenant)
    tasks = await tasks_of(tenant)
    assert [t.status for t in tasks] == ["handled", "open"] and tasks[1].id != first.id
    assert len([r for r in host.provider.requests if r.body == DEFAULT_ACK_TEXT]) == 2


async def test_two_clinics_run_the_whole_flow_side_by_side_without_touching_each_other(monkeypatch, make_tenant):
    host = make_host()
    a, b = await make_tenant(), await make_tenant()
    intake = Intake(monkeypatch, hook=host.fast.after_commit)
    await say(intake, a, "hello a", 1)
    await say(intake, b, "hello b", 1)
    await host.fast.drain()
    (task_a,), (task_b,) = await tasks_of(a), await tasks_of(b)
    host.clock.now = max(task_a.received_at, task_b.received_at) + timedelta(minutes=31)
    await host.scheduler.tick(a)
    assert (await tasks_of(a))[0].escalation_state == "escalated" and (await tasks_of(b))[0].escalation_state == "none"
    await host.scheduler.tick(b)
    assert (await tasks_of(b))[0].escalation_state == "escalated"
    assert len(await audit_rows(a, ACTION)) == 1 and len(await audit_rows(b, ACTION)) == 1


async def test_switching_the_engine_on_late_loses_nothing(monkeypatch, make_tenant):
    state = {"on": False}
    host, tenant, intake = await start(monkeypatch, make_tenant, enabled=lambda: state["on"])
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    assert host.provider.requests == [] and await tasks_of(tenant) == []  # stored, waiting
    host.clock.advance(minutes=40)
    assert (await host.scheduler.tick(tenant)).ran is False
    state["on"] = True
    await host.scheduler.tick(tenant)  # the ack, late, and the task
    (task,) = await tasks_of(tenant)
    assert [r.body for r in host.provider.requests] == [DEFAULT_ACK_TEXT]
    await host.scheduler.tick(tenant)  # the holding message and the escalation are already due
    (task,) = await tasks_of(tenant)
    assert task.holding_sent_at is not None and task.escalation_state == "escalated"


@pytest.mark.parametrize("minutes", [0, 1, 2])
async def test_a_text_is_answered_before_the_first_tick_ever_runs(monkeypatch, make_tenant, minutes):
    host, tenant, intake = await start(monkeypatch, make_tenant)
    await say(intake, tenant, "Hello", 1)
    await host.fast.drain()
    assert len(host.provider.requests) == 1  # no tick has run yet: the fast path did it
