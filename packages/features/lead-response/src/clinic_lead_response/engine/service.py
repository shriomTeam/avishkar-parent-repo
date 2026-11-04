"""The engine: claim due jobs for one clinic and run them.

Two gates, both checked every time work is about to start, never remembered:
  * ``LEAD_RESPONSE_ENGINE_ENABLED`` (off unless set). Off means nothing is claimed and nothing is sent; the jobs
    wait in the table, which is why switching it on later loses nothing.
  * the clinic has the feature (``core.tenant_features``). A clinic without it is never touched.

A handler returns how its job ended (``Done``, ``Cancel`` or ``Wait``) and the engine makes the matching queue call. A
handler that raises is a failed attempt: the job backs off, and after its last attempt becomes ``failed``. What a job
leaves in the table is ids and fixed words only.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_lead_response.config import get_intake_settings
from clinic_lead_response.engine import ack, escalation, help_job, holding
from clinic_lead_response.engine.ports import Clock, JobQueue
from clinic_lead_response.engine.queue import ClaimedJob, PostgresJobQueue
from clinic_lead_response.engine.results import Cancel, Done, End, Wait
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.gateway.service import Gateway

log = logging.getLogger("lead_response.engine")

FEATURE_KEY = "lead_response"
SessionScope = Callable[[uuid.UUID], AbstractAsyncContextManager[AsyncSession]]
Handler = Callable[["Engine", ClaimedJob], Awaitable[End]]


class Engine:
    def __init__(
        self,
        gateway: Gateway,
        *,
        queue: JobQueue | None = None,
        clock: Clock | None = None,
        session_scope: SessionScope | None = None,
        enabled: Callable[[], bool] | None = None,
    ):
        self.gateway = gateway
        self.now: Clock = clock or (lambda: datetime.now(UTC))
        self.scope: SessionScope = session_scope or tenant_session
        self.queue: JobQueue = queue or PostgresJobQueue(clock=self.now, session_scope=self.scope)
        self._enabled = enabled or (lambda: get_intake_settings().engine_enabled)
        self.handlers: dict[str, Handler] = {
            "ack": ack.handle,
            "holding": holding.handle,
            "help": help_job.handle,
            "escalate": escalation.handle,
        }

    async def may_run(self, tenant_id: uuid.UUID) -> bool:
        """The switch is on and the clinic has the feature. Checked at the start of every batch of work."""
        if not self._enabled():
            return False
        async with self.scope(tenant_id) as session:
            return FEATURE_KEY in await enabled_feature_keys(session)

    async def run_due(self, tenant_id: uuid.UUID, *, limit: int = 10) -> int:
        """Claim and run this clinic's due jobs. Returns how many were run."""
        if not await self.may_run(tenant_id):
            return 0
        jobs = await self.queue.claim(tenant_id, limit=limit, kinds=list(self.handlers))
        for job in jobs:
            await self.run_job(job)
        return len(jobs)

    async def run_job(self, job: ClaimedJob) -> None:
        try:
            end = await self.handlers[job.kind](self, job)
        except Exception as error:
            await self.queue.fail_attempt(job, error)
            return
        match end:
            case Done(code=code):
                applied = await self.queue.complete(job, code=code)
            case Cancel(reason=reason):
                applied = await self.queue.cancel(job, reason)
            case Wait(run_at=run_at, count_attempt=count):
                applied = await self.queue.reschedule(job, run_at, count_attempt=count)
        if not applied:
            # The lease ran out while the handler worked and another worker owns the job now. Whatever the handler
            # did is safe to repeat (every send is keyed), so the other worker finishes it.
            log_event(
                log, "job_lease_lost", tenant_id=job.tenant_id, trace_id=job.trace_id, job_id=job.id, job_kind=job.kind
            )
