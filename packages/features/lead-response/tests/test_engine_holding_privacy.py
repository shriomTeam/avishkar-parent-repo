"""The holding wording carries nothing it should not, and nothing personal reaches a log, a job or an audit row."""

import logging
import re

from lr_engine import all_jobs, tasks_of
from lr_gateway import make_lead, set_settings
from lr_intake import LEAD_NUMBER, OUR_NUMBER
from lr_wait import go_to, holdings, open_wait, opt_out, staff_reply
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.ops import AuditLog
from clinic_lead_response.engine.holding import HOLDING_TEXT_PLACEHOLDER

INBOUND_AND_ACK = "Walnut-Harbour our own ack wording, also never logged"
SECRETS = [INBOUND_AND_ACK, "Walnut", LEAD_NUMBER, LEAD_NUMBER[1:], OUR_NUMBER, OUR_NUMBER[1:]]


def test_the_exact_wording_of_the_placeholder():
    assert HOLDING_TEXT_PLACEHOLDER == "Thank you for your patience. Our team has your message."


def test_the_wording_promises_no_time_names_nobody_and_has_no_link_or_personal_data():
    text = HOLDING_TEXT_PLACEHOLDER
    assert not re.search(r"\d", text), "no numbers: no times, no phone numbers"
    for forbidden in ("http", "www", ".com", "@", "minute", "hour", "soon", "shortly", "today", "tomorrow"):
        assert forbidden not in text.lower(), forbidden
    assert "{" not in text and "}" not in text, "no merge fields"
    assert len(text) <= 160, "one SMS segment"
    assert text.isascii()


def test_the_wording_does_not_name_the_clinic_which_is_why_it_needs_approval():
    # Not a feature: a recorded limitation. US carrier rules may expect the business to be identifiable, so the final
    # wording must be approved before the engine is switched on (see the module comment and PROGRESS.md).
    assert "clinic" not in HOLDING_TEXT_PLACEHOLDER.lower()


async def test_a_holding_run_logs_ids_and_no_wording_or_number(make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, ack_text=INBOUND_AND_ACK)
    wait = await open_wait(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    assert len(holdings(wait.provider)) == 1
    lines = [r.getMessage() for r in caplog.records]
    text = " ".join(lines)
    for secret in SECRETS + [HOLDING_TEXT_PLACEHOLDER, "Thank you for your patience"]:
        assert secret not in text, f"{secret!r} reached a log line"
    (line,) = [x for x in lines if x.startswith("holding ")]
    for field in (f"tenant_id={tenant}", "trace_id=", "job_id=", "task_id=", "message_id=", "outcome=sent"):
        assert field in line


async def test_a_cancelled_holding_job_logs_its_reason_and_ids_only(make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("holding_cancelled")]
    assert f"tenant_id={tenant}" in line and "reason=stop" in line and "task_id=" in line
    assert LEAD_NUMBER not in line and LEAD_NUMBER[1:] not in line


async def test_the_holding_and_escalation_jobs_hold_ids_only(make_tenant):
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    for job in await all_jobs(tenant):
        text = f"{job.payload} {job.idempotency_key} {job.last_error_code} {job.cancel_reason}"
        assert HOLDING_TEXT_PLACEHOLDER not in text and "Thank you" not in text
        assert set(job.payload) <= {"message_id", "task_id"}


async def test_the_task_holds_no_wording(make_tenant):
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    (task,) = await tasks_of(tenant)
    assert "Thank you" not in " ".join(str(v) for v in task.__dict__.values())


async def test_holding_and_cancelling_write_no_audit_row(make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await staff_reply(tenant, lead, wait.task.received_at)
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    async with tenant_session(tenant) as session:
        assert await session.scalar(select(AuditLog.id).limit(1)) is None


async def test_every_engine_log_line_of_a_holding_run_names_its_clinic_and_a_trace(make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    wait = await open_wait(tenant, await make_lead(tenant))
    caplog.clear()
    go_to(wait, 15)
    await wait.engine.run_due(tenant)
    lines = [r.getMessage() for r in caplog.records if r.name == "lead_response.engine"]
    assert lines
    for line in lines:
        assert f"tenant_id={tenant}" in line and "trace_id=" in line
