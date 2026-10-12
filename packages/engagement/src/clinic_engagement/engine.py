"""Runs enrolments: sends the next step when due, stops when people book/reply/opt out."""

import logging
import string
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import distinct, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_core.database import current_tenant
from clinic_core.events import APPOINTMENT_BOOKED, CONSENT_CHANGED, MESSAGE_INBOUND, emit
from clinic_core.features import Event, JobContext
from clinic_db.models.core import Consent, Lead, Patient, Tenant
from clinic_db.models.engagement import Enrollment, Message
from clinic_engagement.compliance import STOP_KEYWORDS, can_contact, next_send_window
from clinic_engagement.providers import MessagingProvider, get_provider
from clinic_engagement.sequences import sequence_registry

log = logging.getLogger(__name__)


async def enroll(
    session: AsyncSession,
    *,
    sequence_key: str,
    owner_feature: str,
    patient_id: uuid.UUID | None = None,
    lead_id: uuid.UUID | None = None,
    owner_ref: uuid.UUID | None = None,
    context: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Enrollment:
    seq = sequence_registry()[sequence_key]
    if (patient_id is None) == (lead_id is None):
        raise ValueError("enrol exactly one of patient_id or lead_id")
    now = now or datetime.now(UTC)
    enrollment = Enrollment(
        tenant_id=current_tenant(session),
        sequence_key=sequence_key,
        owner_feature=owner_feature,
        owner_ref=owner_ref,
        patient_id=patient_id,
        lead_id=lead_id,
        next_run_at=now + seq.steps[0].delay,
        context=context or {},
    )
    session.add(enrollment)
    return enrollment


async def stop_for_person(
    session: AsyncSession, *, reason: str, patient_id: uuid.UUID | None = None, lead_id: uuid.UUID | None = None
) -> int:
    cond = Enrollment.patient_id == patient_id if patient_id else Enrollment.lead_id == lead_id
    result = await session.execute(
        update(Enrollment)
        .where(cond, Enrollment.status == "active")
        .values(status="stopped", stop_reason=reason, next_run_at=None)
    )
    return result.rowcount or 0


def _render(template: str, values: dict[str, Any]) -> str:
    return string.Formatter().vformat(template, (), defaultdict(str, values))


async def run_due(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 200,
    provider: MessagingProvider | None = None,
) -> int:
    """Process this tenant's due enrolments. Safe to run from several workers at once."""
    now = now or datetime.now(UTC)
    provider = provider or get_provider()
    tenant = await session.get(Tenant, current_tenant(session))
    registry = sequence_registry()
    due = (
        await session.scalars(
            select(Enrollment)
            .where(Enrollment.status == "active", Enrollment.next_run_at <= now)
            .order_by(Enrollment.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()

    for enr in due:
        seq = registry.get(enr.sequence_key)
        if seq is None or enr.step_index >= len(seq.steps):
            enr.status, enr.stop_reason, enr.next_run_at = "stopped", "unknown_sequence", None
            continue
        window = next_send_window(now, tenant.timezone)
        if window > now:
            enr.next_run_at = window
            continue

        step = seq.steps[enr.step_index]
        person = await session.get(Patient, enr.patient_id) if enr.patient_id else await session.get(Lead, enr.lead_id)
        to = person.phone if step.channel == "sms" else person.email
        allowed, reason = await can_contact(session, tenant, enr.patient_id, step.channel)
        if not to:
            allowed, reason = False, f"no_{step.channel}_address"

        body = _render(
            step.template,
            {
                "first_name": person.first_name or "there",
                "clinic_name": tenant.name,
                "booking_link": tenant.settings.get("booking_url", ""),
                **enr.context,
            },
        )
        msg = Message(
            tenant_id=tenant.id,
            enrollment_id=enr.id,
            patient_id=enr.patient_id,
            lead_id=enr.lead_id,
            channel=step.channel,
            to_address=to or "",
            body=body,
        )
        session.add(msg)

        if not allowed:
            msg.status = "blocked"
            msg.meta = {"reason": reason}
            enr.status, enr.stop_reason, enr.next_run_at = "stopped", reason, None
            continue

        if step.channel == "sms":
            sent = await provider.send_sms(to, body)
        else:
            sent = await provider.send_email(
                to, _render(step.subject or tenant.name, {"clinic_name": tenant.name}), body
            )
        msg.status = "sent" if sent.ok else "failed"
        msg.provider_message_id, msg.sent_at = sent.provider_message_id, now if sent.ok else None
        if sent.error:
            msg.meta = {"error": sent.error}

        enr.step_index += 1
        if enr.step_index < len(seq.steps):
            enr.next_run_at = now + seq.steps[enr.step_index].delay
        else:
            enr.status, enr.next_run_at = "completed", None
    return len(due)


async def tenants_with_due_work(system: AsyncSession, now: datetime | None = None) -> list[uuid.UUID]:
    """Cross-tenant scan; call with a system_session()."""
    now = now or datetime.now(UTC)
    rows = await system.scalars(
        select(distinct(Enrollment.tenant_id)).where(Enrollment.status == "active", Enrollment.next_run_at <= now)
    )
    return list(rows)


# --- platform event handlers (run for every tenant, not gated by entitlements) ----


async def _on_booked(ctx: JobContext, event: Event) -> None:
    if patient_id := event.payload.get("patient_id"):
        await stop_for_person(ctx.session, reason="booked", patient_id=uuid.UUID(patient_id))


async def _on_inbound(ctx: JobContext, event: Event) -> None:
    patient_id = event.payload.get("patient_id")
    lead_id = event.payload.get("lead_id")
    pid = uuid.UUID(patient_id) if patient_id else None
    lid = uuid.UUID(lead_id) if lead_id else None
    body = (event.payload.get("body") or "").strip().lower()
    if body in STOP_KEYWORDS:
        if pid:
            ctx.session.add(
                Consent(
                    tenant_id=ctx.tenant_id,
                    patient_id=pid,
                    kind=event.payload.get("channel", "sms"),
                    granted=False,
                    source="sms_stop_keyword",
                    evidence={"event_id": event.id},
                )
            )
            await emit(ctx.session, CONSENT_CHANGED, {"patient_id": patient_id, "kind": "sms", "granted": False})
            await audit(ctx.session, "consent.revoked", actor_type="system", entity_type="patient", entity_id=pid)
        await stop_for_person(ctx.session, reason="opted_out", patient_id=pid, lead_id=lid)
    else:
        # A human reply goes to the front desk inbox; automation stops talking.
        await stop_for_person(ctx.session, reason="replied", patient_id=pid, lead_id=lid)


PLATFORM_EVENT_HANDLERS = {
    APPOINTMENT_BOOKED: [_on_booked],
    MESSAGE_INBOUND: [_on_inbound],
}
