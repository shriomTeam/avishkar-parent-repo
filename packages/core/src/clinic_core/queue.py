"""BullMQ queues (Redis). Uses the official Python port of BullMQ, so jobs are
interoperable with the Node BullMQ client if Next.js ever needs to enqueue."""

import uuid
from typing import Any

from bullmq import Queue

from clinic_core.settings import get_settings

JOBS_QUEUE = "clinic-jobs"  # feature jobs: {"tenant_id", "data"}
EVENTS_QUEUE = "clinic-events"  # relayed outbox events

_queues: dict[str, Queue] = {}


def get_queue(name: str) -> Queue:
    if name not in _queues:
        _queues[name] = Queue(name, {"connection": get_settings().redis_url})
    return _queues[name]


async def enqueue(job: str, tenant_id: uuid.UUID, data: dict[str, Any] | None = None, **opts: Any) -> None:
    """Enqueue ``<feature>.<job>`` for one tenant."""
    await get_queue(JOBS_QUEUE).add(
        job,
        {"tenant_id": str(tenant_id), "data": data or {}},
        {"removeOnComplete": 1000, "removeOnFail": 5000, **opts},
    )


async def close_queues() -> None:
    for q in _queues.values():
        await q.close()
    _queues.clear()
