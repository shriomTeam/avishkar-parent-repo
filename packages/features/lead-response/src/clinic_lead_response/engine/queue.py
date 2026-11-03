"""The ``jobs`` table as a queue.

A claim is a lease. ``claim`` pushes the job's ``run_at`` forward by the lease and stamps ``locked_at`` (the lease
token), and leaves the status ``pending``. So a worker that dies simply lets the lease run out: the job is due again,
found by the same partial index as every other due job, with no scan for "stuck" rows. Every later call names the token
it was given; if the lease has been lost to another claim, the call changes nothing and says so, so a slow worker cannot
undo the work of the one that took over. Two workers claiming at once never get the same job
(``FOR UPDATE SKIP LOCKED``).

Attempts count claims. A job that keeps dying (a crash counts) reaches ``max_attempts`` and becomes ``failed``: that is
the dead-letter state, kept in the table with the reason, never retried. A job that is only waiting (not yet due, or the
gateway asked for a retry) is put back without counting.

Only ids, kinds and fixed reason words are stored or logged. An exception's text can hold anything, so only its class
name is kept.
"""

import logging
import uuid
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant, tenant_session
from clinic_db.models.lead_response import Job
from clinic_lead_response.engine.ports import Clock
from clinic_lead_response.gateway.log import log_event

log = logging.getLogger("lead_response.engine")

LEASE_SECONDS = 120  # longer than a provider call (8 s) with room for the steps around it
BACKOFF_SECONDS = (30, 120, 480)  # after the 1st, 2nd and 3rd failed attempt
LEASE_EXPIRED = "lease_expired"
MAX_CODE_LENGTH = 64  # jobs.last_error_code is a String(64)

SessionScope = Callable[[uuid.UUID], AbstractAsyncContextManager[AsyncSession]]


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    idempotency_key: str
    conversation_id: uuid.UUID | None
    task_id: uuid.UUID | None
    trace_id: uuid.UUID | None
    attempts: int  # including this claim
    max_attempts: int
    token: datetime  # the lease: the job's locked_at as stamped by this claim
    payload: dict = field(default_factory=dict, repr=False)  # ids only


def error_code(error: BaseException | str) -> str:
    """What may be stored about a failure: the exception's class name, or a fixed word. Never its message."""
    name = error if isinstance(error, str) else type(error).__name__
    return name[:MAX_CODE_LENGTH]


async def enqueue_job(
    session: AsyncSession,
    *,
    kind: str,
    key: str,
    run_at: datetime,
    conversation_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    payload: dict | None = None,
    trace_id: uuid.UUID | None = None,
    max_attempts: int | None = None,
) -> bool:
    """Add a job inside the caller's transaction. False when the key was already used, so a job is never added twice."""
    values = {
        "tenant_id": current_tenant(session),
        "kind": kind,
        "run_at": run_at,
        "idempotency_key": key,
        "conversation_id": conversation_id,
        "task_id": task_id,
        "payload": payload or {},
        "trace_id": trace_id,
    }
    if max_attempts is not None:
        values["max_attempts"] = max_attempts
    statement = (
        insert(Job)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
        .returning(Job.id)
    )
    return await session.scalar(statement) is not None


class PostgresJobQueue:
    def __init__(
        self,
        *,
        clock: Clock | None = None,
        session_scope: SessionScope | None = None,
        lease_seconds: int = LEASE_SECONDS,
    ):
        self._now = clock or (lambda: datetime.now(UTC))
        self._scope = session_scope or tenant_session
        self._lease = timedelta(seconds=lease_seconds)

    async def claim(
        self, tenant_id: uuid.UUID, *, limit: int = 10, kinds: Sequence[str] | None = None
    ) -> list[ClaimedJob]:
        """Lease up to ``limit`` due jobs. First, jobs whose lease ran out on their last allowed attempt are
        dead-lettered instead of being run again."""
        now = self._now()
        async with self._scope(tenant_id) as session:
            dead = await session.execute(
                update(Job)
                .where(Job.status == "pending", Job.run_at <= now, Job.attempts >= Job.max_attempts)
                .values(status="failed", last_error_code=LEASE_EXPIRED, finished_at=now, locked_at=None)
                .returning(Job.id, Job.kind, Job.trace_id)
                .execution_options(synchronize_session=False)
            )
            for job_id, kind, trace_id in dead.all():
                log_event(
                    log,
                    "job_dead",
                    level=logging.ERROR,
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    job_id=job_id,
                    job_kind=kind,
                    reason=LEASE_EXPIRED,
                )
            wanted = [Job.status == "pending", Job.run_at <= now, Job.attempts < Job.max_attempts]
            if kinds is not None:
                wanted.append(Job.kind.in_(list(kinds)))
            # Lock the rows first, then change exactly those. (One UPDATE with this as a subquery can be planned so that
            # it locks and changes a different set than the limit says.) The locks last until the commit.
            due = (
                select(Job.id)
                .where(*wanted)
                .order_by(Job.run_at, Job.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            ids = list(await session.scalars(due))
            claimed = await session.execute(
                update(Job)
                .where(Job.id.in_(ids))
                .values(locked_at=now, run_at=now + self._lease, attempts=Job.attempts + 1)
                .returning(Job)
                .execution_options(synchronize_session=False)
            )
            jobs = list(claimed.scalars())
        return [
            ClaimedJob(
                id=j.id,
                tenant_id=tenant_id,
                kind=j.kind,
                idempotency_key=j.idempotency_key,
                conversation_id=j.conversation_id,
                task_id=j.task_id,
                trace_id=j.trace_id,
                attempts=j.attempts,
                max_attempts=j.max_attempts,
                token=j.locked_at,
                payload=dict(j.payload or {}),
            )
            for j in sorted(jobs, key=lambda job: (job.created_at, job.id))
        ]

    async def _finish(self, job: ClaimedJob, **values) -> bool:
        """Change the job only while the caller still holds the lease it was given."""
        async with self._scope(job.tenant_id) as session:
            result = await session.execute(
                update(Job)
                .where(Job.id == job.id, Job.status == "pending", Job.locked_at == job.token)
                .values(**values)
                .returning(Job.id)
                .execution_options(synchronize_session=False)
            )
            return result.first() is not None

    async def complete(self, job: ClaimedJob, *, code: str | None = None) -> bool:
        """Done. ``code`` is a fixed word for how it ended when that is worth keeping (for example ``blocked``)."""
        return await self._finish(
            job, status="done", finished_at=self._now(), locked_at=None, last_error_code=code and error_code(code)
        )

    async def cancel(self, job: ClaimedJob, reason: str) -> bool:
        return await self._finish(
            job, status="cancelled", cancel_reason=reason[:32], finished_at=self._now(), locked_at=None
        )

    async def reschedule(self, job: ClaimedJob, run_at: datetime, *, count_attempt: bool = False) -> bool:
        """Put the job back to run at ``run_at``. Waiting is not failing, so by default this claim is not counted."""
        attempts = Job.attempts if count_attempt else Job.attempts - 1
        return await self._finish(job, run_at=run_at, locked_at=None, attempts=attempts)

    async def fail_attempt(self, job: ClaimedJob, error: BaseException | str) -> str | None:
        """The attempt blew up. ``"retry"`` with a backoff, or ``"failed"`` once the allowed attempts are used. None
        when the lease was lost."""
        code = error_code(error)
        if job.attempts >= job.max_attempts:
            done = await self._finish(
                job, status="failed", last_error_code=code, finished_at=self._now(), locked_at=None
            )
            outcome = "failed"
        else:
            delay = BACKOFF_SECONDS[min(job.attempts, len(BACKOFF_SECONDS)) - 1]
            done = await self._finish(
                job, run_at=self._now() + timedelta(seconds=delay), locked_at=None, last_error_code=code
            )
            outcome = "retry"
        if not done:
            return None
        log_event(
            log,
            "job_failed" if outcome == "failed" else "job_retry",
            level=logging.ERROR if outcome == "failed" else logging.WARNING,
            tenant_id=job.tenant_id,
            trace_id=job.trace_id,
            job_id=job.id,
            job_kind=job.kind,
            attempt=job.attempts,
            reason=code,
        )
        return outcome
