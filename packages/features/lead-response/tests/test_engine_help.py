"""The help job: the wording is still a placeholder, so the engine sends nothing and says why."""

import logging

from lr_engine import add_job, all_jobs, get_job, jobs_of_kind, make_engine, messages_of, tasks_of
from lr_gateway import make_lead
from lr_intake import LEAD_NUMBER, Counter, Intake, sid, twilio_pairs

from clinic_lead_response.engine import help_job


async def help_text(intake, tenant, n=1, body="HELP"):
    assert (await intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=body))).status_code == 200


def after_the_texts():
    engine, provider, clock = make_engine()
    clock.advance(seconds=2)
    return engine, provider


async def test_a_help_job_is_cancelled_with_the_reason_and_nothing_is_sent(monkeypatch, make_tenant):
    tenant = await make_tenant()
    await help_text(Intake(monkeypatch), tenant)
    engine, provider = after_the_texts()
    assert await engine.run_due(tenant) == 1
    (job,) = await jobs_of_kind(tenant, "help")
    assert (job.status, job.cancel_reason, job.locked_at) == ("cancelled", "help_wording_pending", None)
    assert job.finished_at is not None
    assert provider.requests == [] and [m for m in await messages_of(tenant) if m.direction == "outbound"] == []


async def test_a_help_job_makes_no_task_and_no_timers(monkeypatch, make_tenant):
    tenant = await make_tenant()
    await help_text(Intake(monkeypatch), tenant)
    engine, _ = after_the_texts()
    await engine.run_due(tenant)
    assert await tasks_of(tenant) == []
    assert [j.kind for j in await all_jobs(tenant)] == ["help"]


async def test_the_reason_is_a_fixed_word_that_fits_the_column():
    assert help_job.CANCEL_REASON == "help_wording_pending" and len(help_job.CANCEL_REASON) <= 32


async def test_a_help_job_is_not_run_twice(monkeypatch, make_tenant):
    tenant = await make_tenant()
    await help_text(Intake(monkeypatch), tenant)
    engine, provider = after_the_texts()
    assert await engine.run_due(tenant) == 1
    assert await engine.run_due(tenant) == 0
    assert provider.requests == []


async def test_every_help_job_is_cancelled(monkeypatch, make_tenant):
    tenant = await make_tenant()
    intake = Intake(monkeypatch)
    for n in range(1, 5):
        await help_text(intake, tenant, n=n, body="help")
    engine, provider = after_the_texts()
    assert await engine.run_due(tenant) == 4
    assert {(j.status, j.cancel_reason) for j in await jobs_of_kind(tenant, "help")} == {
        ("cancelled", "help_wording_pending")
    }
    assert provider.requests == []


async def test_a_help_job_from_an_opted_out_contact_ends_the_same_way(make_tenant):
    tenant = await make_tenant()
    await make_lead(tenant, consent=(False, "stop"))
    engine, provider, clock = make_engine()
    await add_job(tenant, kind="help", run_at=clock(), payload={"message_id": "x"})
    await engine.run_due(tenant)
    assert (await jobs_of_kind(tenant, "help"))[0].cancel_reason == "help_wording_pending" and provider.requests == []


async def test_with_the_switch_off_a_help_job_waits(monkeypatch, make_tenant):
    tenant = await make_tenant()
    await help_text(Intake(monkeypatch), tenant)
    engine, _, clock = make_engine(enabled=False)
    clock.advance(seconds=2)
    assert await engine.run_due(tenant) == 0
    job = (await jobs_of_kind(tenant, "help"))[0]
    assert (await get_job(tenant, job.id)).status == "pending"


async def test_a_help_job_costs_only_the_gates_the_claim_and_the_cancel(monkeypatch, make_tenant):
    tenant = await make_tenant()
    await help_text(Intake(monkeypatch), tenant)
    engine, _ = after_the_texts()
    with Counter() as statements:
        await engine.run_due(tenant)
    print(f"\nhelp job: {len(statements)} statements")
    assert len(statements) <= 2 + 4 + 2  # the two gates, the claim, then set_config and the update that cancels it


async def test_the_help_job_logs_its_ids_and_the_reason_and_nothing_personal(monkeypatch, make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    await help_text(Intake(monkeypatch), tenant)
    engine, _ = after_the_texts()
    await engine.run_due(tenant)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("help_skipped")]
    assert f"tenant_id={tenant}" in line and "job_id=" in line and "reason=help_wording_pending" in line
    assert LEAD_NUMBER not in line and LEAD_NUMBER[1:] not in line


async def test_an_ordinary_text_is_not_mistaken_for_help(monkeypatch, make_tenant):
    tenant = await make_tenant()
    intake = Intake(monkeypatch)
    await help_text(intake, tenant, body="I need help with my appointment")
    engine, provider = after_the_texts()
    await engine.run_due(tenant)
    assert await jobs_of_kind(tenant, "help") == [] and len(provider.requests) == 1
