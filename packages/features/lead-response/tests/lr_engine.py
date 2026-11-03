"""Helpers for the engine tests: a queue on a fake clock, and jobs written straight into the table.
Every id and word here is made up; nothing can reach the network."""

import uuid
from datetime import datetime

from lr_gateway import DAYTIME, Clock
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import Job
from clinic_lead_response.engine.queue import PostgresJobQueue

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
