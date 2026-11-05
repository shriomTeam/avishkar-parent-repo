"""No message text, phone number or wording reaches a log line, an audit row, a job or a task."""

import logging

from lr_engine import all_jobs, jobs_of_kind, make_engine, seed_text, tasks_of
from lr_gateway import FakeProvider, accepted, audit_rows, make_lead, set_settings
from lr_intake import LEAD_NUMBER, OUR_NUMBER
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.ops import AuditLog

INBOUND = "Zebra-Quartz inbound wording that must never be logged"
ACK_WORDING = "Walnut-Harbour our own ack wording, also never logged"
SECRETS = [INBOUND, ACK_WORDING, "Zebra", "Walnut", LEAD_NUMBER, LEAD_NUMBER[1:], OUR_NUMBER, OUR_NUMBER[1:]]


def clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"{secret!r} reached the output"


async def run_once(make_tenant, caplog, provider=None, **lead_kw):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    lead = await make_lead(tenant, **lead_kw)
    await set_settings(tenant, ack_text=ACK_WORDING)
    await seed_text(tenant, lead, body=INBOUND)
    engine, provider, clock = make_engine(provider)
    clock.advance(seconds=1)
    await engine.run_due(tenant)
    return tenant, lead, provider


async def test_a_sent_ack_logs_ids_and_no_wording_or_number(make_tenant, caplog):
    tenant, _, provider = await run_once(make_tenant, caplog)
    assert provider.requests[0].body == ACK_WORDING  # it really was sent, so the logs had every chance to leak it
    lines = [r.getMessage() for r in caplog.records]
    assert lines
    clean(" ".join(lines))
    (ack,) = [line for line in lines if line.startswith("ack ")]
    assert f"tenant_id={tenant}" in ack and "trace_id=" in ack and "job_id=" in ack and "task_id=" in ack
    assert "outcome=sent" in ack and "message_id=" in ack


async def test_blocked_skipped_and_failed_acks_log_no_personal_value(make_tenant, caplog):
    await run_once(make_tenant, caplog, consent=(False, "stop"))
    caplog.clear()
    await run_once(make_tenant, caplog, provider=FakeProvider(accepted("SM" + "1" * 32)), phone=None)
    clean(" ".join(r.getMessage() for r in caplog.records))


async def test_a_provider_that_raises_leaves_only_the_class_name(make_tenant, caplog):
    class Raising:
        name = "raising"

        async def send(self, request):
            raise RuntimeError(f"cannot reach {LEAD_NUMBER} with {ACK_WORDING} {INBOUND}")

    tenant, _, _ = await run_once(make_tenant, caplog, provider=Raising())
    (ack,) = await jobs_of_kind(tenant, "ack")
    # the gateway treats a raising adapter as an uncertain send, so the job ends; nothing of the text is kept anywhere
    clean(f"{ack.last_error_code} {ack.cancel_reason} {ack.payload}")
    clean(" ".join(r.getMessage() for r in caplog.records))


async def test_a_handler_that_blows_up_stores_the_class_name_not_the_message(make_tenant, caplog, monkeypatch):
    from clinic_lead_response.engine import ack

    async def boom(*args, **kwargs):
        raise ValueError(f"{INBOUND} {LEAD_NUMBER}")

    monkeypatch.setattr(ack, "ensure_task", boom)
    tenant, _, _ = await run_once(make_tenant, caplog)
    (job,) = await jobs_of_kind(tenant, "ack")
    assert job.last_error_code == "ValueError" and job.status == "pending"
    clean(" ".join(r.getMessage() for r in caplog.records))
    assert "job_retry" in " ".join(r.getMessage() for r in caplog.records)


async def test_jobs_hold_ids_only(make_tenant, caplog):
    tenant, _, _ = await run_once(make_tenant, caplog)
    for job in await all_jobs(tenant):
        clean(f"{job.payload} {job.idempotency_key} {job.last_error_code} {job.cancel_reason}")
        assert set(job.payload) <= {"message_id", "task_id"}


async def test_the_task_holds_no_wording_and_no_number(make_tenant, caplog):
    tenant, _, _ = await run_once(make_tenant, caplog)
    (task,) = await tasks_of(tenant)
    clean(" ".join(str(v) for v in task.__dict__.values()))


async def test_the_ack_path_writes_no_audit_row(make_tenant, caplog):
    tenant, _, _ = await run_once(make_tenant, caplog)
    async with tenant_session(tenant) as session:
        assert await session.scalar(select(AuditLog.id).limit(1)) is None
    assert await audit_rows(tenant, "lead_response.consent.changed") == []


async def test_every_log_line_the_engine_writes_names_its_clinic_and_a_trace(make_tenant, caplog):
    tenant, _, _ = await run_once(make_tenant, caplog)
    engine_lines = [r.getMessage() for r in caplog.records if r.name == "lead_response.engine"]
    assert engine_lines
    for line in engine_lines:
        assert f"tenant_id={tenant}" in line and "trace_id=" in line
