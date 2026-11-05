"""The tick: what runs every minute for each clinic that has the feature.

The platform's worker hosts it. It lists a feature's ``jobs`` and ``schedules`` and, for every clinic that has the
feature, enqueues ``<feature>.<job>`` once per interval; the job runs in that clinic's session. So the tick is a plain
job (``tick``) plus a schedule of 60 seconds, registered in ``feature.py``, and needs no change to the worker or the
platform. There is NO loop inside the API: if nothing runs the worker, the timers (holding message, escalation) wait in
the ``jobs`` table, and the first thing a lead gets, the ack, is sent by the fast path (``fast_path.py``) while an API
instance is alive. See PROGRESS.md for the hosting risk.

``Scheduler`` is the seam: anything that can say "this clinic's turn" calls ``tick(tenant_id)``. One tick, in order:
  1. the gates (the engine switch, then the clinic has the feature). With the switch off nothing is read at all;
  2. the stuck-message sweep (settle messages left ``sending``);
  3. the due jobs, in batches, up to ``MAX_JOBS_PER_TICK``; anything left waits for the next tick.
Every job is leased while it runs, so two ticks at once (two workers, or a tick and the fast path) never run a job
twice.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Protocol

from clinic_lead_response.engine import sweep
from clinic_lead_response.gateway.log import log_event

log = logging.getLogger("lead_response.engine")

TICK_JOB = "tick"  # the platform names it lead_response.tick
TICK_EVERY_SECONDS = 60
BATCH = 10
MAX_JOBS_PER_TICK = 100


@dataclass(frozen=True)
class TickReport:
    ran: bool = False  # the gates were open
    stuck_expired: int = 0
    jobs_run: int = 0


class Scheduler(Protocol):
    async def tick(self, tenant_id: uuid.UUID) -> TickReport: ...


class EngineScheduler:
    def __init__(self, engine, *, batch: int = BATCH, max_jobs: int = MAX_JOBS_PER_TICK):
        self._engine = engine
        self._batch = batch
        self._max_jobs = max_jobs

    async def tick(self, tenant_id: uuid.UUID) -> TickReport:
        engine = self._engine
        if not await engine.may_run(tenant_id):
            return TickReport()
        trace_id = uuid.uuid4()  # one per tick, for the log lines; the jobs carry their own
        expired = await sweep.expire_stuck(engine, tenant_id, checked=True)
        total = 0
        while total < self._max_jobs:
            ran = await engine.run_due(tenant_id, limit=self._batch, checked=True)
            total += ran
            if ran < self._batch:
                break
        if expired or total:
            log_event(log, "tick", tenant_id=tenant_id, trace_id=trace_id, outcome="worked", queries=total + expired)
        return TickReport(True, expired, total)
