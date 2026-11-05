"""The escalation: the clinic's staff response target was missed, so the task is flagged for a manager.

In release 1 it notifies nobody. It marks the task (``escalation_state = 'escalated'``, ``escalated_at``) and writes ONE
audit row, ``lead_response.task.escalated``, that records the task, the conversation, the trace and the ROLE to be
told (``owner`` or ``office_manager``, from the clinic's settings): ids and a role, nothing else, no phone number and no
text. The dashboard shows the flag. No message is sent to anyone and no platform event is emitted: a notifier can be
added later without touching this. The task stays open: escalating does not answer the lead and does not close anything.

The target is wall-clock time: ``received_at + sla_minutes``, with ``sla_minutes`` read from the settings when the job
FIRES. If the clinic has since lengthened the target the job puts itself back to the new time (without counting an
attempt). A shortened target reaches only waits that begin afterwards: the job of a wait already open was timed when its
task was made and fires then. The role is read at the same moment.

The job asks first whether escalating is still wanted, with the same rules and the same order as the holding message
(``waits.reason_to_stop``, see ``contract.py``): the task is no longer open (``handled`` or ``task_closed``), staff have
answered (``staff_reply``, and ``first_staff_reply_at`` is filled in if the API has not), or the contact opted out
(``stop``; the task stays open). Then it looks again and writes in ONE short transaction that holds a row lock on the
task, so a change to the task made by the reply API cannot slip in between the look and the write. What remains is a
window of milliseconds in which a staff reply (a row in ``messages``, which that lock does not cover) can land after
the second look and before the commit: the task is flagged although staff have just answered. That is harmless (the
flag is information for a manager, and the reply is on the task), and it cannot be closed without locking the
conversation.

Once per task: the update only changes a task whose state is still ``none``, and the audit row is written only by the
run that changed it, in the same transaction, so a repeated run, a second escalation job or two workers at once leave
one flag, one time and one audit row.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_db.models.lead_response import Task
from clinic_lead_response.engine.results import Cancel, Done, End, Wait
from clinic_lead_response.engine.waits import TaskView, load_wait, reason_to_stop
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.settings_store import current_settings

log = logging.getLogger("lead_response.engine")

ACTION = "lead_response.task.escalated"
ENTITY = "lead_response_task"
NOT_ESCALATED = "none"
ESCALATED = "escalated"


async def handle(engine, job) -> End:
    try:
        task_id = job.task_id or uuid.UUID(str(job.payload["task_id"]))
    except (KeyError, ValueError):
        return Cancel("bad_payload")
    trace_id = job.trace_id or uuid.uuid4()

    early = await _look(engine, job, task_id)
    if early is not None:
        return early
    return await _escalate(engine, job, task_id, trace_id)


async def _look(engine, job, task_id: uuid.UUID) -> End | None:
    """The decision: is the wait over, is it too early, is it already done? None means go on to escalate."""
    now = engine.now()
    async with engine.scope(job.tenant_id) as session:
        task = await load_wait(session, task_id)
        if task is None:
            return Cancel("task_missing")
        over = await reason_to_stop(session, task, job_id=job.id, now=now)
        if over is not None:
            _log_cancelled(job, task_id, over.reason)
            return over
        _version, settings = await current_settings(session)  # read now, at fire time
        due = task.received_at + timedelta(minutes=settings.sla_minutes)
        if now < due:
            return Wait(due)
        if task.escalation_state != NOT_ESCALATED:
            return Done("already_escalated")
    return None


async def _escalate(engine, job, task_id: uuid.UUID, trace_id: uuid.UUID) -> End:
    """The second look and the write, in one short transaction holding a lock on the task row."""
    now = engine.now()
    async with engine.scope(job.tenant_id) as session:
        task = await _load_locked(session, task_id)
        if task is None:
            return Cancel("task_missing")
        over = await reason_to_stop(session, task, job_id=job.id, now=now)
        if over is not None:
            _log_cancelled(job, task_id, over.reason)
            return over
        _version, settings = await current_settings(session)
        changed = await session.scalar(
            update(Task)
            .where(Task.id == task_id, Task.escalation_state == NOT_ESCALATED)
            .values(escalation_state=ESCALATED, escalated_at=now)
            .returning(Task.id)
        )
        if changed is None:
            return Done("already_escalated")
        await audit(
            session,
            ACTION,
            actor_type="system",
            entity_type=ENTITY,
            entity_id=task_id,
            details={
                "role": settings.escalation_role,
                "task_id": str(task_id),
                "conversation_id": str(task.conversation_id),
                "trace_id": str(trace_id),
            },
        )
    log_event(
        log,
        "escalated",
        tenant_id=job.tenant_id,
        trace_id=trace_id,
        job_id=job.id,
        task_id=task_id,
        outcome="escalated",
    )
    return Done()


async def _load_locked(session: AsyncSession, task_id: uuid.UUID) -> TaskView | None:
    """The task row, locked until this transaction ends."""
    row = (
        await session.execute(
            select(
                Task.id,
                Task.status,
                Task.received_at,
                Task.conversation_id,
                Task.contact_id,
                Task.holding_sent_at,
                Task.first_staff_reply_at,
                Task.escalation_state,
            )
            .where(Task.id == task_id)
            .with_for_update()
        )
    ).first()
    return TaskView(*row) if row else None


def _log_cancelled(job, task_id: uuid.UUID, reason: str) -> None:
    log_event(
        log,
        "escalation_cancelled",
        tenant_id=job.tenant_id,
        trace_id=job.trace_id,
        job_id=job.id,
        task_id=task_id,
        reason=reason,
    )
