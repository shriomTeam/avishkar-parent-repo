"""Reading and ending a wait: the checks that run before a holding message or an escalation, and the writes that follow.

Every function takes a tenant session. See ``contract.py`` for what the engine counts as a staff reply and as handled.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.lead_response import Job, Message, Task
from clinic_lead_response.engine.contract import (
    CANCEL_HANDLED,
    CANCEL_STAFF_REPLY,
    CANCEL_STOP,
    CANCEL_TASK_CLOSED,
    STAFF_SENDER_KIND,
    TASK_HANDLED,
    TASK_OPEN,
)
from clinic_lead_response.engine.results import Cancel
from clinic_lead_response.gateway import store as gateway_store
from clinic_lead_response.gateway.policy import current_consent

TIMER_KINDS = ("holding", "escalate")


@dataclass(frozen=True)
class TaskView:
    """A task as the timers see it."""

    id: uuid.UUID
    status: str
    received_at: datetime
    conversation_id: uuid.UUID
    contact_id: uuid.UUID
    holding_sent_at: datetime | None
    first_staff_reply_at: datetime | None
    escalation_state: str


async def load_wait(session: AsyncSession, task_id: uuid.UUID) -> TaskView | None:
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
            ).where(Task.id == task_id)
        )
    ).first()
    return TaskView(*row) if row else None


async def first_staff_reply_at(session: AsyncSession, conversation_id: uuid.UUID, since: datetime) -> datetime | None:
    """When staff first answered after ``since`` (the contract: an outbound ``staff`` message), or None."""
    return await session.scalar(
        select(func.min(Message.created_at)).where(
            Message.conversation_id == conversation_id,
            Message.direction == "outbound",
            Message.sender_kind == STAFF_SENDER_KIND,
            Message.created_at >= since,
        )
    )


async def opted_out(session: AsyncSession, contact_id: uuid.UUID) -> bool:
    """The newest consent record says no (a STOP, or the carrier reporting one)."""
    return current_consent(await gateway_store.consent_snapshots(session, contact_id, "sms")).granted is False


async def cancel_timers(
    session: AsyncSession, task_id: uuid.UUID, reason: str, *, now: datetime, keep: uuid.UUID | None = None
) -> int:
    """Cancel the task's pending holding and escalation jobs, except ``keep`` (the job that is deciding). A job that is
    being run right now is cancelled too: its own finishing call is fenced and finds that out."""
    conditions = [Job.task_id == task_id, Job.kind.in_(TIMER_KINDS), Job.status == "pending"]
    if keep is not None:
        conditions.append(Job.id != keep)
    result = await session.execute(
        update(Job)
        .where(*conditions)
        .values(status="cancelled", cancel_reason=reason, finished_at=now, locked_at=None)
        .returning(Job.id)
        .execution_options(synchronize_session=False)
    )
    return len(result.all())


async def reason_to_stop(session: AsyncSession, wait: TaskView, *, job_id: uuid.UUID, now: datetime) -> Cancel | None:
    """Is this wait over, or the lead beyond automatic messages? If so, cancel the timers and say why.

    Order: the task is no longer open, then staff have answered, then the contact opted out. A STOP ends the automatic
    messages only; the task stays open."""
    if wait.status != TASK_OPEN:
        reason = CANCEL_HANDLED if wait.status == TASK_HANDLED else CANCEL_TASK_CLOSED
    else:
        replied_at = await first_staff_reply_at(session, wait.conversation_id, wait.received_at)
        if replied_at is not None:
            await mark_staff_reply(session, wait.id, replied_at)
            reason = CANCEL_STAFF_REPLY
        elif await opted_out(session, wait.contact_id):
            reason = CANCEL_STOP
        else:
            return None
    await cancel_timers(session, wait.id, reason, now=now, keep=job_id)
    return Cancel(reason)


async def mark_staff_reply(session: AsyncSession, task_id: uuid.UUID, when: datetime) -> None:
    """Fill in ``first_staff_reply_at`` if the reply API has not. Never overwritten."""
    await session.execute(
        update(Task).where(Task.id == task_id, Task.first_staff_reply_at.is_(None)).values(first_staff_reply_at=when)
    )


async def mark_holding_sent(session: AsyncSession, task_id: uuid.UUID, when: datetime) -> None:
    await session.execute(
        update(Task).where(Task.id == task_id, Task.holding_sent_at.is_(None)).values(holding_sent_at=when)
    )
