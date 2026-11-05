"""What the escalation records is ids and a role, and nothing personal reaches a log, a job, a task or an audit row."""

import logging
import uuid

from lr_engine import all_jobs, tasks_of
from lr_gateway import audit_rows, make_lead, set_settings
from lr_intake import LEAD_NUMBER, OUR_NUMBER
from lr_wait import go_to, open_wait, opt_out
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Message
from clinic_db.models.ops import AuditLog
from clinic_lead_response.engine.holding import HOLDING_TEXT_PLACEHOLDER

ACTION = "lead_response.task.escalated"
ACK_WORDING = "Walnut-Harbour our own ack wording, also never recorded"
SECRETS = [ACK_WORDING, "Walnut", HOLDING_TEXT_PLACEHOLDER, LEAD_NUMBER, LEAD_NUMBER[1:], OUR_NUMBER, OUR_NUMBER[1:]]


async def escalated(make_tenant, caplog=None):
    if caplog is not None:
        caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    await set_settings(tenant, ack_text=ACK_WORDING, escalation_role="owner")
    wait = await open_wait(tenant, lead)
    go_to(wait, 16)
    await wait.engine.run_due(tenant)
    go_to(wait, 30)
    await wait.engine.run_due(tenant)
    return tenant, lead, wait


def clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"{secret!r} reached the output"


async def test_the_audit_row_holds_exactly_the_role_and_three_ids(make_tenant):
    tenant, lead, _ = await escalated(make_tenant)
    (row,) = await audit_rows(tenant, ACTION)
    (task,) = await tasks_of(tenant)
    assert (row.actor_type, row.actor_id, row.entity_type, row.entity_id) == (
        "system",
        None,
        "lead_response_task",
        task.id,
    )
    assert set(row.details) == {"role", "task_id", "conversation_id", "trace_id"}
    assert row.details == {
        "role": "owner",
        "task_id": str(task.id),
        "conversation_id": str(lead.conversation),
        "trace_id": str(task.trace_id),
    }


async def test_the_role_is_one_of_the_two_the_settings_allow(make_tenant):
    tenant, _, _ = await escalated(make_tenant)
    (row,) = await audit_rows(tenant, ACTION)
    assert row.details["role"] in {"owner", "office_manager"}
    for key in ("task_id", "conversation_id", "trace_id"):
        uuid.UUID(row.details[key])  # a real id, not free text


async def test_no_wording_or_number_is_in_the_audit_row(make_tenant):
    tenant, _, _ = await escalated(make_tenant)
    async with tenant_session(tenant) as session:
        rows = list(await session.scalars(select(AuditLog)))
    assert len(rows) == 1
    clean(" ".join(str(v) for r in rows for v in (r.actor_id, r.action, r.entity_type, r.entity_id, r.details)))


async def test_no_log_line_carries_wording_or_numbers(make_tenant, caplog):
    tenant, _, _ = await escalated(make_tenant, caplog)
    lines = [r.getMessage() for r in caplog.records]
    assert lines
    clean(" ".join(lines))
    (line,) = [x for x in lines if x.startswith("escalated ")]
    for field in (f"tenant_id={tenant}", "trace_id=", "job_id=", "task_id=", "outcome=escalated"):
        assert field in line


async def test_the_role_is_not_written_to_the_log(make_tenant, caplog):
    await escalated(make_tenant, caplog)
    assert "owner" not in " ".join(r.getMessage() for r in caplog.records if r.getMessage().startswith("escalated "))


async def test_a_cancelled_escalation_logs_a_reason_and_ids_only(make_tenant, caplog):
    caplog.set_level(logging.DEBUG, logger="lead_response")
    tenant = await make_tenant()
    lead = await make_lead(tenant)
    wait = await open_wait(tenant, lead)
    await opt_out(tenant, lead)
    go_to(wait, 31)
    await wait.engine.run_due(tenant)
    (line,) = [r.getMessage() for r in caplog.records if r.getMessage().startswith("escalation_cancelled")]
    assert f"tenant_id={tenant}" in line and "reason=stop" in line and "task_id=" in line
    clean(line)


async def test_the_jobs_and_the_task_hold_no_wording_or_numbers(make_tenant):
    tenant, _, _ = await escalated(make_tenant)
    for job in await all_jobs(tenant):
        clean(f"{job.payload} {job.idempotency_key} {job.last_error_code} {job.cancel_reason}")
    (task,) = await tasks_of(tenant)
    clean(" ".join(str(v) for v in task.__dict__.values()))


async def test_escalating_added_no_message_and_the_messages_hold_no_escalation_text(make_tenant):
    tenant, _, _ = await escalated(make_tenant)
    async with tenant_session(tenant) as session:
        kinds = sorted(await session.scalars(select(Message.sender_kind)))
    assert kinds == ["ack", "contact", "holding"]  # the text, our ack and our holding message; nothing for the manager


async def test_every_engine_log_line_of_the_escalation_names_its_clinic_and_a_trace(make_tenant, caplog):
    tenant, _, _ = await escalated(make_tenant, caplog)
    engine_lines = [r.getMessage() for r in caplog.records if r.name == "lead_response.engine"]
    assert engine_lines
    for line in engine_lines:
        assert f"tenant_id={tenant}" in line and "trace_id=" in line
