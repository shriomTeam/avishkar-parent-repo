"""Cloud Tasks dispatch, backed by the encrypted database queue for lost-task recovery."""

import asyncio
import json
import logging
from datetime import timedelta

from sqlalchemy import or_, select

from clinic_core.auth.security import now
from clinic_core.database import system_session
from clinic_core.settings import get_settings
from clinic_db.models.membership import EmailDelivery

TASK_PATH = "/tasks/email/send"
# Recreate a task if it was lost/exhausted or the publisher died before create_task.
DISPATCH_LEASE = timedelta(minutes=15)
PENDING = ("queued", "retry", "sending")


def _create_task(settings, ident, generation):
    from google.api_core.exceptions import AlreadyExists
    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2

    with tasks_v2.CloudTasksClient() as client:
        parent = client.queue_path(
            settings.email_tasks_project, settings.email_tasks_region, settings.email_tasks_queue
        )
        task = {
            "name": f"{parent}/tasks/email-{ident}-g{generation}",
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": settings.email_tasks_url + TASK_PATH,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"delivery_id": str(ident)}).encode(),
                "oidc_token": {
                    "service_account_email": settings.email_tasks_invoker_email,
                    "audience": settings.email_tasks_audience,
                },
            },
            "dispatch_deadline": duration_pb2.Duration(seconds=60),
        }
        try:
            client.create_task(request={"parent": parent, "task": task}, timeout=3, retry=None)
        except AlreadyExists:
            pass  # Same generation already reached Cloud Tasks.


async def publish(delivery_id, settings=None):
    """Reserve before publishing. Failed or interrupted publication cannot lose the DB record."""
    settings = settings or get_settings()
    async with system_session(database_url=settings.database_system_url) as db:
        row = await db.get(EmailDelivery, delivery_id, with_for_update=True)
        if not row or row.status not in PENDING or row.next_attempt_at > now():
            return 0
        if row.task_dispatch_at and row.task_dispatch_at > now() - DISPATCH_LEASE:
            return 0
        row.task_generation += 1
        row.task_dispatch_at = now()
        generation = row.task_generation
    try:
        await asyncio.to_thread(_create_task, settings, delivery_id, generation)
        return 1
    except Exception:
        # No payload, recipient, token or provider diagnostics in logs.
        logging.getLogger("email.tasks").warning("Email task enqueue deferred to durable recovery")
        async with system_session(database_url=settings.database_system_url) as db:
            row = await db.get(EmailDelivery, delivery_id, with_for_update=True)
            if row and row.task_generation == generation:
                row.task_dispatch_at = None
        return 0


async def dispatch_due(settings=None, *, limit=20):
    """Cloud production reconciles task dispatch; local development sends due records directly."""
    settings = settings or get_settings()
    if not settings.email_tasks_queue:
        from clinic_engagement.email.service import deliver_due

        return await deliver_due(settings, limit=limit)
    async with system_session(database_url=settings.database_system_url) as db:
        ids = list(
            await db.scalars(
                select(EmailDelivery.id)
                .where(
                    EmailDelivery.status.in_(PENDING),
                    EmailDelivery.next_attempt_at <= now(),
                    or_(
                        EmailDelivery.task_dispatch_at.is_(None),
                        EmailDelivery.task_dispatch_at <= now() - DISPATCH_LEASE,
                    ),
                )
                .order_by(EmailDelivery.next_attempt_at, EmailDelivery.id)
                .limit(limit)
            )
        )
    count = 0
    for ident in ids:
        count += await publish(ident, settings)
    return count
