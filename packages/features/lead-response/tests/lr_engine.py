"""Helpers for the engine tests: a queue on a fake clock, and jobs written straight into the table.
Every id and word here is made up; nothing can reach the network."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from lr_gateway import DAYTIME, Clock, FakeProvider, Lead, gateway
from lr_intake import sid
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Job, Message, Task
from clinic_lead_response.engine.queue import PostgresJobQueue
from clinic_lead_response.engine.service import Engine
from clinic_lead_response.gateway.service import Gateway

NOW = DAYTIME  # 15:00 UTC on 1 May 2026: 11:00 in New York, outside any quiet hours


def make_queue(clock: Clock | None = None, **kwargs) -> tuple[PostgresJobQueue, Clock]:
    clock = clock or Clock(NOW)
    return PostgresJobQueue(clock=clock, **kwargs), clock


async def add_job(
    tenant: uuid.UUID,
    *,
    kind: str = "ack",
    run_at: datetime = NOW,
    key: str | None = None,
    status: str = "pending",
    attempts: int = 0,
    max_attempts: int = 3,
    payload: dict | None = None,
    trace_id: uuid.UUID | None = None,
    locked_at: datetime | None = None,
) -> uuid.UUID:
    job_id = uuid.uuid4()
    async with tenant_session(tenant) as session:
        session.add(
            Job(
                id=job_id,
                tenant_id=tenant,
                kind=kind,
                run_at=run_at,
                status=status,
                idempotency_key=key or f"{kind}:{job_id}",
                attempts=attempts,
                max_attempts=max_attempts,
                payload=payload or {},
                trace_id=trace_id,
                locked_at=locked_at,
            )
        )
    return job_id


async def get_job(tenant: uuid.UUID, job_id: uuid.UUID) -> Job:
    async with tenant_session(tenant) as session:
        return await session.scalar(select(Job).where(Job.id == job_id))


async def all_jobs(tenant: uuid.UUID) -> list[Job]:
    async with tenant_session(tenant) as session:
        return list(await session.scalars(select(Job).order_by(Job.created_at, Job.id)))


# --- the engine on a fake clock and a fake provider (the clock starts at the real time: intake and the database stamp
# --- jobs and messages with real time, so a fake clock set to another date would never find a job due) ---------------


def real_clock() -> Clock:
    return Clock(datetime.now(UTC))


def make_engine(
    provider: FakeProvider | None = None,
    *,
    clock: Clock | None = None,
    enabled: bool | Callable[[], bool] = True,
    number: str | None = "+14155550100",
    queue=None,
) -> tuple[Engine, FakeProvider, Clock]:
    clock = clock or real_clock()
    provider = provider or FakeProvider()
    sender: Gateway = gateway(provider, clock=clock, number=number)
    return (
        Engine(sender, clock=clock, enabled=enabled if callable(enabled) else (lambda: enabled), queue=queue),
        provider,
        clock,
    )


async def seed_text(
    tenant: uuid.UUID,
    lead: Lead,
    *,
    n: int = 1,
    body: str = "Hello, are you open on Monday?",
    created_at: datetime | None = None,
    run_at: datetime | None = None,
    job: bool = True,
    trace_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """An inbound text and (unless ``job`` is False) the ack job intake would have written. Returns the message id."""
    message_id, trace = uuid.uuid4(), trace_id or uuid.uuid4()
    when = created_at or datetime.now(UTC)
    async with tenant_session(tenant) as session:
        session.add(
            Message(
                id=message_id,
                tenant_id=tenant,
                conversation_id=lead.conversation,
                direction="inbound",
                channel="sms",
                sender_kind="contact",
                body=body,
                provider="twilio",
                provider_message_id=sid(n),
                idempotency_key=f"in:{sid(n)}",
                trace_id=trace,
                created_at=when,
            )
        )
        await session.flush()
        if job:
            session.add(
                Job(
                    tenant_id=tenant,
                    kind="ack",
                    run_at=run_at or when,
                    idempotency_key=f"ack:{message_id}",
                    conversation_id=lead.conversation,
                    payload={"message_id": str(message_id)},
                    trace_id=trace,
                )
            )
    return message_id


async def add_outbound(
    tenant: uuid.UUID, lead: Lead, *, sender_kind: str, created_at: datetime, staff: bool = False, n: int = 1
) -> uuid.UUID:
    """An earlier message from us (an ack, a holding message, a staff reply), stamped at ``created_at``."""
    message_id = uuid.uuid4()
    async with tenant_session(tenant) as session:
        session.add(
            Message(
                id=message_id,
                tenant_id=tenant,
                conversation_id=lead.conversation,
                direction="outbound",
                channel="sms",
                sender_kind=sender_kind,
                body="earlier message",
                provider="fake",
                idempotency_key=f"seed-out:{message_id}",
                created_at=created_at,
            )
        )
    return message_id


async def tasks_of(tenant: uuid.UUID) -> list[Task]:
    async with tenant_session(tenant) as session:
        return list(await session.scalars(select(Task).order_by(Task.created_at, Task.id)))


async def jobs_of_kind(tenant: uuid.UUID, kind: str) -> list[Job]:
    return [j for j in await all_jobs(tenant) if j.kind == kind]


async def messages_of(tenant: uuid.UUID) -> list[Message]:
    async with tenant_session(tenant) as session:
        return list(await session.scalars(select(Message).order_by(Message.created_at, Message.id)))


def around(clock: Clock, hours: int = 1) -> dict:
    """A quiet-hours window (in UTC, so make the clinic's zone UTC) that contains the clock's time."""
    start, end = clock() - timedelta(hours=hours), clock() + timedelta(hours=hours)
    return {"start": start.strftime("%H:%M"), "end": end.strftime("%H:%M")}
