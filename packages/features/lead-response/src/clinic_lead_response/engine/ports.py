"""The seams the engine is built on, so a different queue or clock can be plugged in without touching the rules."""

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from clinic_lead_response.engine.queue import ClaimedJob

Clock = Callable[[], datetime]


class JobQueue(Protocol):
    """A queue of jobs, one tenant at a time. A claim is a lease: until it expires nobody else gets the job, and every
    later call names the lease it holds, so a worker that lost its lease cannot change a job someone else now owns."""

    async def claim(
        self, tenant_id: uuid.UUID, *, limit: int = 10, kinds: Sequence[str] | None = None
    ) -> "list[ClaimedJob]": ...

    async def complete(self, job: "ClaimedJob", *, code: str | None = None) -> bool: ...

    async def cancel(self, job: "ClaimedJob", reason: str) -> bool: ...

    async def reschedule(self, job: "ClaimedJob", run_at: datetime, *, count_attempt: bool = False) -> bool: ...

    async def fail_attempt(self, job: "ClaimedJob", error: BaseException | str) -> str | None: ...
