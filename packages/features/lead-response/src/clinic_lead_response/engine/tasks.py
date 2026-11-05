"""The priority task and what the engine reads around it. Every function takes a tenant session, so row-level security
applies, and nothing here takes an id from outside the tenant: the message, conversation and contact are found through
the job's own message id.

A "wait" is the life of one open task. There is at most one open task per conversation (a unique index), so a second
text during a wait joins the task that is already open instead of starting another.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.lead_response import Conversation, Message, Task
from clinic_lead_response.engine.queue import enqueue_job

HOLDING_JOB = "holding"
ESCALATE_JOB = "escalate"


@dataclass(frozen=True)
class Inbound:
    """The text a job is about."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID
    contact_id: uuid.UUID
    received_at: datetime  # when we stored it


@dataclass(frozen=True)
class TaskRef:
    id: uuid.UUID
    received_at: datetime
    first_ack_at: datetime | None
    created: bool  # made by this call


async def load_inbound(session: AsyncSession, message_id: uuid.UUID) -> Inbound | None:
    row = (
        await session.execute(
            select(Message.id, Message.conversation_id, Conversation.contact_id, Message.created_at)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Message.direction == "inbound")
        )
    ).first()
    return Inbound(*row) if row else None


async def ensure_task(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID,
    contact_id: uuid.UUID,
    received_at: datetime,
    trace_id: uuid.UUID,
) -> TaskRef:
    """The open task for this conversation, made if there is none. Safe to call twice and from two workers: the unique
    index lets one insert win, and the other finds it. The wait is dated from the text that started it."""
    for _ in range(3):
        made = (
            await session.execute(
                insert(Task)
                .values(
                    tenant_id=current_tenant(session),
                    conversation_id=conversation_id,
                    contact_id=contact_id,
                    status="open",
                    priority=0,
                    received_at=received_at,
                    trace_id=trace_id,
                )
                .on_conflict_do_nothing(index_elements=["conversation_id"], index_where=text("status = 'open'"))
                .returning(Task.id, Task.received_at, Task.first_ack_at)
            )
        ).first()
        if made is not None:
            return TaskRef(*made, created=True)
        found = (
            await session.execute(
                select(Task.id, Task.received_at, Task.first_ack_at).where(
                    Task.conversation_id == conversation_id, Task.status == "open"
                )
            )
        ).first()
        if found is not None:
            return TaskRef(*found, created=False)
        # It was closed between the conflict and the read: the wait is over, so make the next one.
    raise RuntimeError("could not find or make the open task")


async def schedule_timers(
    session: AsyncSession,
    task: TaskRef,
    *,
    conversation_id: uuid.UUID,
    trace_id: uuid.UUID,
    holding_minutes: int,
    sla_minutes: int,
) -> None:
    """The holding message and the escalation, due at the settings' times counted from the start of the wait. They are
    written with the task, so they exist even if the acknowledgement fails. Each reads the settings again when it
    fires."""
    for kind, key, minutes in (
        (HOLDING_JOB, f"holding:{task.id}", holding_minutes),
        (ESCALATE_JOB, f"escalate:{task.id}", sla_minutes),
    ):
        await enqueue_job(
            session,
            kind=kind,
            key=key,
            run_at=task.received_at + timedelta(minutes=minutes),
            conversation_id=conversation_id,
            task_id=task.id,
            payload={"task_id": str(task.id)},
            trace_id=trace_id,
        )


async def mark_first_ack(session: AsyncSession, task_id: uuid.UUID, when: datetime) -> None:
    await session.execute(update(Task).where(Task.id == task_id, Task.first_ack_at.is_(None)).values(first_ack_at=when))


async def staff_replied_since(session: AsyncSession, conversation_id: uuid.UUID, since: datetime) -> bool:
    """A staff member has answered: an outbound text from staff after the wait began. This is the contract with the
    reply API (a later chunk): a staff reply is a ``messages`` row, direction outbound, sender_kind ``staff``."""
    return bool(
        await session.scalar(
            select(
                exists().where(
                    Message.conversation_id == conversation_id,
                    Message.direction == "outbound",
                    Message.sender_kind == "staff",
                    Message.created_at >= since,
                )
            )
        )
    )


async def latest_outbound_at(session: AsyncSession, conversation_id: uuid.UUID) -> datetime | None:
    return await session.scalar(
        select(func.max(Message.created_at)).where(
            Message.conversation_id == conversation_id, Message.direction == "outbound"
        )
    )


async def sent_since(session: AsyncSession, conversation_id: uuid.UUID, sender_kind: str, since: datetime) -> int:
    """How many automatic messages of this kind we have made for the conversation since ``since``, whatever became of
    them. Blocked ones count too, so the cap is on tries, not only on texts that went out."""
    return await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == "outbound",
            Message.sender_kind == sender_kind,
            Message.created_at >= since,
        )
    )
