"""Background worker.

Runs four things in one process (scale horizontally by running more copies):
  * jobs     - ``<feature>.<job>`` handlers from installed features (BullMQ)
  * events   - fans each outbox event out to platform handlers and to the handlers
               of features the event's tenant has enabled (BullMQ)
  * relay    - moves committed rows from ops.outbox_events onto the events queue
  * ticks    - engagement sends and feature schedules
"""

import asyncio
import logging
import signal
import uuid
from datetime import UTC, datetime

from bullmq import Worker
from redis.asyncio import Redis
from sqlalchemy import select, update

from clinic_core.database import dispose_engines, system_session, tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_core.features import Event, EventHandler, JobContext, JobHandler, job_name, load_features
from clinic_core.queue import EVENTS_QUEUE, JOBS_QUEUE, close_queues, enqueue, get_queue
from clinic_core.settings import get_settings
from clinic_db.models.core import TenantFeature
from clinic_db.models.ops import OutboxEvent
from clinic_engagement import PLATFORM_EVENT_HANDLERS, run_due, tenants_with_due_work

log = logging.getLogger("clinic_worker")

RELAY_INTERVAL = 1.0
ENGAGEMENT_INTERVAL = 30.0


def _job_handlers() -> dict[str, JobHandler]:
    return {job_name(f.key, name): h for f in load_features().values() for name, h in f.jobs.items()}


def _event_handlers() -> dict[str, list[tuple[str | None, EventHandler]]]:
    """event type -> [(feature key or None for platform handlers, handler)]"""
    out: dict[str, list[tuple[str | None, EventHandler]]] = {}
    for event_type, handlers in PLATFORM_EVENT_HANDLERS.items():
        out.setdefault(event_type, []).extend((None, h) for h in handlers)
    for f in load_features().values():
        for event_type, handlers in f.event_handlers.items():
            out.setdefault(event_type, []).extend((f.key, h) for h in handlers)
    return out


async def process_job(job, token) -> None:
    handler = _job_handlers().get(job.name)
    if handler is None:
        raise RuntimeError(f"no handler for job {job.name}")
    tenant_id = uuid.UUID(job.data["tenant_id"])
    async with tenant_session(tenant_id) as session:
        feature_key = job.name.split(".", 1)[0]
        if feature_key not in await enabled_feature_keys(session):
            log.info("skipping %s: feature disabled for tenant %s", job.name, tenant_id)
            return
        await handler(JobContext(tenant_id=tenant_id, session=session), job.data.get("data", {}))


async def process_event(job, token) -> None:
    d = job.data
    event = Event(
        id=d["id"],
        tenant_id=uuid.UUID(d["tenant_id"]),
        type=d["type"],
        payload=d["payload"],
        created_at=datetime.fromisoformat(d["created_at"]),
    )
    handlers = _event_handlers().get(event.type, [])
    if not handlers:
        return
    async with tenant_session(event.tenant_id) as session:
        enabled = await enabled_feature_keys(session)
    failures = []
    # Each handler gets its own transaction, so one feature's bug can't roll back another's work.
    # A failure retries the whole event: handlers must be idempotent.
    for feature_key, handler in handlers:
        if feature_key is not None and feature_key not in enabled:
            continue
        try:
            async with tenant_session(event.tenant_id) as session:
                await handler(JobContext(tenant_id=event.tenant_id, session=session), event)
        except Exception:
            log.exception("event %s handler %s failed", event.type, getattr(handler, "__qualname__", handler))
            failures.append(feature_key or "platform")
    if failures:
        raise RuntimeError(f"event {event.id} failed in {failures}")


async def relay_outbox_once(limit: int = 500) -> int:
    queue = get_queue(EVENTS_QUEUE)
    async with system_session() as s:
        events = (
            await s.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.published_at.is_(None))
                .order_by(OutboxEvent.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for e in events:
            await queue.add(
                e.event_type,
                {
                    "id": e.id,
                    "tenant_id": str(e.tenant_id),
                    "type": e.event_type,
                    "payload": e.payload,
                    "created_at": e.created_at.isoformat(),
                },
                {
                    "jobId": f"evt-{e.id}",
                    "attempts": 5,
                    "backoff": {"type": "exponential", "delay": 2000},
                    "removeOnComplete": 1000,
                    "removeOnFail": 5000,
                },
            )
        if events:
            await s.execute(
                update(OutboxEvent)
                .where(OutboxEvent.id.in_([e.id for e in events]))
                .values(published_at=datetime.now(UTC))
            )
    return len(events)


async def engagement_tick_once() -> int:
    async with system_session() as s:
        tenants = await tenants_with_due_work(s)
    sent = 0
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            sent += await run_due(session)
    return sent


async def schedules_tick(redis: Redis) -> None:
    """Enqueue each feature schedule for every tenant that has the feature, at most once per
    interval across all worker processes (Redis lock)."""
    for f in load_features().values():
        for sched in f.schedules:
            name = job_name(f.key, sched.job)
            if not await redis.set(f"clinic:schedule:{name}", "1", nx=True, ex=sched.every_seconds):
                continue
            async with system_session() as s:
                tenants = (
                    await s.scalars(
                        select(TenantFeature.tenant_id).where(
                            TenantFeature.feature_key == f.key, TenantFeature.enabled.is_(True)
                        )
                    )
                ).all()
            for tenant_id in tenants:
                await enqueue(name, tenant_id)


async def _every(seconds: float, fn, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await fn()
        except Exception:
            log.exception("periodic task %s failed", fn.__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:
            pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    features = load_features()
    log.info("features installed: %s", ", ".join(features) or "(none)")
    log.info("job handlers: %s", ", ".join(_job_handlers()) or "(none)")

    opts = {"connection": settings.redis_url, "concurrency": 10}
    workers = [Worker(JOBS_QUEUE, process_job, opts), Worker(EVENTS_QUEUE, process_event, opts)]
    redis = Redis.from_url(settings.redis_url)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    tasks = [
        asyncio.create_task(_every(RELAY_INTERVAL, relay_outbox_once, stop)),
        asyncio.create_task(_every(ENGAGEMENT_INTERVAL, engagement_tick_once, stop)),
        asyncio.create_task(_every(30, lambda: schedules_tick(redis), stop)),
    ]
    await stop.wait()
    log.info("shutting down")
    await asyncio.gather(*tasks)
    for w in workers:
        await w.close()
    await redis.aclose()
    await close_queues()
    await dispose_engines()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
