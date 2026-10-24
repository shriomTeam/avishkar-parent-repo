"""Reusable, feature-independent transactional email; credentials never reach clients."""

import asyncio
import json
import logging
import secrets
import uuid
from datetime import timedelta

import httpx
from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import select

from clinic_core.auth.security import now
from clinic_core.database import system_session
from clinic_core.settings import get_settings
from clinic_db.models.membership import EmailDelivery
from clinic_db.models.ops import OutboxEvent
from clinic_engagement.email.sendgrid import EmailFailure, send_email
from clinic_engagement.email.types import EmailContent


def cipher(settings):
    keys = [
        settings.email_payload_encryption_key.get_secret_value(),
        *filter(None, settings.email_old_payload_keys.get_secret_value().split(",")),
    ]
    return MultiFernet([Fernet(key.encode()) for key in keys])


def valid_email(value):
    from clinic_core.email import normalize_email

    return normalize_email(value)


async def enqueue_email(
    db,
    *,
    tenant_id,
    to: list[str],
    template: EmailContent,
    deduplication_key: str,
    settings=None,
    invitation_id=None,
    generation=None,
):
    settings = settings or get_settings()
    if len(to) != 1:
        raise ValueError("Queue each recipient separately to protect recipient privacy")
    recipient = valid_email(to[0])
    if any(c in template.subject for c in "\r\n"):
        raise ValueError("Invalid subject")
    existing = await db.scalar(
        select(EmailDelivery).where(
            EmailDelivery.tenant_id == tenant_id, EmailDelivery.deduplication_key == deduplication_key
        )
    )
    if existing:
        return existing
    ident = uuid.uuid4()
    payload = json.dumps(
        {
            "to": recipient,
            "subject": template.subject,
            "text": template.text,
            "html": template.html,
            "tenant_id": str(tenant_id),
            "delivery_id": str(ident),
        }
    ).encode()
    encrypted = cipher(settings).encrypt(payload).decode()
    delivery = EmailDelivery(
        id=ident,
        tenant_id=tenant_id,
        deduplication_key=deduplication_key,
        payload=encrypted,
        invitation_id=invitation_id,
        generation=generation,
        next_attempt_at=now(),
        status="queued",
        attempts=0,
    )
    db.add(delivery)
    await db.flush()
    db.add(OutboxEvent(tenant_id=tenant_id, event_type="email.queued", payload={"delivery_id": str(delivery.id)}))
    return delivery


async def deliver_email(delivery_id, settings=None):
    """Dispatch one committed email via Cloud Tasks, or send directly in local development.

    Await this after leaving the enqueue transaction, inside the active API request.
    Test/console providers intentionally keep mail queued for a captured dispatcher.
    """
    settings = settings or get_settings()
    if settings.email_provider != "sendgrid":
        return 0
    try:
        async with asyncio.timeout(5):
            if settings.email_tasks_queue:
                from clinic_engagement.email.tasks import publish

                return await publish(delivery_id, settings)
            return await deliver_due(settings, delivery_id=delivery_id, limit=1)
    except Exception:
        # Never turn a committed invitation into a failed HTTP request or log secrets.
        logging.getLogger("email.delivery").warning("Immediate email attempt deferred to durable retry")
        return 0


async def deliver_due(settings=None, *, sender=None, limit=20, delivery_id=None):
    """Durable leases survive crashes/Redis loss. Network calls happen outside row locks."""
    settings = settings or get_settings()
    if settings.email_provider not in {"sendgrid", "test"}:
        return 0
    sent = 0
    for _ in range(limit):
        async with system_session(database_url=settings.database_system_url) as db:
            query = select(EmailDelivery).where(
                EmailDelivery.status.in_(["queued", "retry", "sending"]), EmailDelivery.next_attempt_at <= now()
            )
            if delivery_id is not None:
                query = query.where(EmailDelivery.id == delivery_id)
            delivery = await db.scalar(
                query.order_by(EmailDelivery.next_attempt_at).limit(1).with_for_update(skip_locked=True)
            )
            if not delivery:
                break
            if delivery.invitation_id:
                from clinic_core.tenancy.invitations import dispatch_allowed

                if not await dispatch_allowed(db, delivery):
                    delivery.status, delivery.payload = "cancelled", None
                    continue
            if delivery.attempts >= 5 or not delivery.payload:
                delivery.status, delivery.payload = "failed", None
                continue
            delivery.status, delivery.attempts = "sending", delivery.attempts + 1
            delivery.next_attempt_at = now() + timedelta(minutes=2)
            ident, attempt, ciphertext, tenant_id = delivery.id, delivery.attempts, delivery.payload, delivery.tenant_id
        error, permanent, message_id, retry_after = None, False, None, 0
        try:
            payload = json.loads(cipher(settings).decrypt(ciphertext.encode(), ttl=7 * 86400))
            if payload.get("tenant_id") != str(tenant_id) or payload.get("delivery_id") != str(ident):
                raise ValueError("Email payload binding mismatch")
            content = EmailContent(payload["subject"], payload["text"], payload["html"])
            message_id = await (
                sender(to=payload["to"], template=content)
                if sender
                else send_email(to=payload["to"], template=content, settings=settings)
            )
        except EmailFailure as exc:
            retry_after = exc.retry_after
            error, permanent = f"provider_{exc.status}", 400 <= exc.status < 500 and exc.status not in {408, 429}
        except (httpx.HTTPError, TimeoutError):
            error = "provider_unavailable"
        except Exception:
            error, permanent = "email_configuration_error", True
        async with system_session(database_url=settings.database_system_url) as db:
            row = await db.get(EmailDelivery, ident, with_for_update=True)
            if row.status != "sending" or row.attempts != attempt:
                continue
            row.error = error
            if error:
                row.status = "failed" if permanent or attempt >= 5 else "retry"
                row.next_attempt_at = now() + timedelta(
                    seconds=max(retry_after, min(3600, 30 * 2**attempt)) + secrets.randbelow(10)
                )
            else:
                row.status, row.provider_message_id = "accepted", message_id
                sent += 1
            if row.status in {"accepted", "failed"}:
                row.payload = None
    return sent
