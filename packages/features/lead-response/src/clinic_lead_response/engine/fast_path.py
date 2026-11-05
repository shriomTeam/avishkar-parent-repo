"""The fast path: answer a lead within seconds, without waiting for the minute tick.

The intake route calls ``after_commit`` once a text is stored (and its keyword applied), before it answers Twilio. With
the engine switched off it returns at once and reads nothing. With it on:
  1. it claims an ack job (the job intake just wrote, or the oldest due one) and runs ``ack.prepare`` AWAITED, within
     ``CHEAP_PART_SECONDS``: the task and its two timer jobs are written and committed, and the decision whether an ack
     is due is made. This is the SAME function the ack job handler uses, so there is one implementation;
  2. if an ack is due, ``ack.deliver`` (the send) is started as a BACKGROUND task and the hook returns, so the route's
     200 never waits for the provider.
Safety nets, all of them the job row: the claim is a lease, so if the instance is frozen or killed before the send (a
serverless instance can be frozen right after it has answered), the lease runs out and the next tick runs the job; the
gateway key makes that second run a "duplicate", never a second text. A background task that fails records a failed
attempt on its job (class name only). Background tasks are kept by strong reference until they finish, are limited to
``max_background`` at a time (when all slots are busy the job is handed straight back to the tick), and nothing in them
can change what the route returns.
"""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING

from clinic_lead_response.engine import ack
from clinic_lead_response.gateway.log import log_event

if TYPE_CHECKING:
    from clinic_lead_response.intake.service import Accepted

log = logging.getLogger("lead_response.engine")

MAX_BACKGROUND_SENDS = 20
CHEAP_PART_SECONDS = 0.25  # the task and timers must not make the 200 late; past this the job is handed to the tick


class FastPath:
    def __init__(
        self,
        engine,
        *,
        max_background: int = MAX_BACKGROUND_SENDS,
        cheap_part_seconds: float = CHEAP_PART_SECONDS,
        spawn: Callable[[Coroutine], object] | None = None,
    ):
        self._engine = engine
        self._slots = asyncio.Semaphore(max_background)
        self._cheap = cheap_part_seconds
        self._tasks: set[asyncio.Task] = set()
        self._spawn = spawn or self._start

    @property
    def pending(self) -> int:
        """Background sends that have not finished."""
        return len(self._tasks)

    async def drain(self) -> None:
        """Wait for the background sends (for tests and an orderly shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def after_commit(self, accepted: "Accepted") -> None:
        if accepted.tenant_id is None or not accepted.ack_queued:
            return
        engine, tenant_id = self._engine, accepted.tenant_id
        if not await engine.may_run(tenant_id):
            return
        jobs = await engine.queue.claim(tenant_id, limit=1, kinds=["ack"])
        if not jobs:
            return
        (job,) = jobs
        try:
            async with asyncio.timeout(self._cheap):
                ready = await ack.prepare(engine, job)
        except TimeoutError:
            await self._hand_back(job, "cheap_part_slow")
            return
        except Exception as error:
            self._log(job, "fast_path_failed", error.__class__.__name__)
            await engine.queue.fail_attempt(job, error)
            return
        if not isinstance(ready, ack.Ready):
            await engine.finish(job, ready)  # nothing to send (a staff reply, an ack already made, a cap)
            return
        if self._slots.locked():
            await self._hand_back(job, "all_slots_busy")
            return
        await self._slots.acquire()  # not locked, so this does not wait
        self._spawn(self._send(job, ready))

    async def _send(self, job, ready) -> None:
        engine = self._engine
        try:
            end = await ack.deliver(engine, job, ready)
            await engine.finish(job, end)
        except Exception as error:
            self._log(job, "fast_path_failed", error.__class__.__name__)
            try:
                await engine.queue.fail_attempt(job, error)
            except Exception:
                self._log(job, "fast_path_failed", "fail_attempt")
        finally:
            self._slots.release()

    async def _hand_back(self, job, reason: str) -> None:
        """Give the job straight back to the tick: due now, not leased, no attempt counted."""
        self._log(job, "fast_path_handed_back", reason)
        await self._engine.queue.reschedule(job, self._engine.now())

    def _start(self, coroutine: Coroutine) -> None:
        task = asyncio.get_running_loop().create_task(coroutine)
        self._tasks.add(task)  # a strong reference: an unreferenced task can be collected before it finishes
        task.add_done_callback(self._tasks.discard)

    def _log(self, job, event: str, reason: str) -> None:
        log_event(
            log,
            event,
            level=logging.WARNING,
            tenant_id=job.tenant_id,
            trace_id=job.trace_id,
            job_id=job.id,
            reason=reason,
        )
