import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.core import Appointment, AppointmentStatus, Patient, Tenant
from clinic_db.models.reviews import Campaign, Integration, ReviewRequest
from clinic_engagement.compliance import can_contact


@dataclass(frozen=True)
class Eligibility:
    ok: bool
    reason: str | None = None
    channel: str | None = None


def _ids(values: list | None) -> set[str]:
    return {str(v) for v in (values or []) if v}


async def applicable_campaigns(session: AsyncSession, appointment: Appointment) -> list[Campaign]:
    campaigns = (
        await session.scalars(
            select(Campaign).where(Campaign.status == "active", Campaign.trigger_type == "appointment_completed")
        )
    ).all()
    matched: list[Campaign] = []
    service_id = str(appointment.service_id) if appointment.service_id else None
    for campaign in campaigns:
        included, excluded = _ids(campaign.included_service_ids), _ids(campaign.excluded_service_ids)
        if excluded and service_id in excluded:
            continue
        if included and (service_id is None or service_id not in included):
            continue
        matched.append(campaign)
    return matched


async def already_processed(session: AsyncSession, appointment_id: uuid.UUID, campaign_id: uuid.UUID) -> bool:
    return (
        await session.scalar(
            select(ReviewRequest.id).where(
                ReviewRequest.appointment_id == appointment_id, ReviewRequest.campaign_id == campaign_id
            )
        )
        is not None
    )


async def evaluate(
    session: AsyncSession,
    *,
    tenant: Tenant,
    campaign: Campaign,
    appointment: Appointment,
    patient: Patient,
    now: datetime,
    exclude_request_id: uuid.UUID | None = None,
) -> Eligibility:
    if appointment.status != AppointmentStatus.COMPLETED:
        return Eligibility(False, "appointment_not_completed")
    if campaign.status != "active":
        return Eligibility(False, "campaign_inactive")
    if tenant.status not in ("active", "trial"):
        return Eligibility(False, "practice_inactive")
    integration = await session.scalar(select(Integration))
    if integration is None or integration.status != "connected" or not integration.google_review_url:
        return Eligibility(False, "google_profile_unavailable")

    channels = list(campaign.channels or ["sms"])
    chosen: str | None = None
    last_contact_reason: str | None = None
    for channel in channels:
        if channel == "sms" and not patient.phone:
            last_contact_reason = "missing_phone"
            continue
        if channel == "email" and not patient.email:
            last_contact_reason = "missing_email"
            continue
        allowed, reason = await can_contact(session, tenant, patient.id, channel)
        if not allowed:
            last_contact_reason = reason
            if not campaign.fallback_enabled:
                return Eligibility(False, reason or "consent_denied")
            continue
        chosen = channel
        break
    if chosen is None:
        return Eligibility(False, last_contact_reason or "no_usable_channel")

    window_start = now - timedelta(days=campaign.frequency_days)
    recent_q = select(ReviewRequest.id).where(
        ReviewRequest.patient_id == patient.id,
        ReviewRequest.campaign_id == campaign.id,
        ReviewRequest.status.notin_(("skipped", "cancelled")),
        ReviewRequest.created_at >= window_start,
    )
    if exclude_request_id is not None:
        recent_q = recent_q.where(ReviewRequest.id != exclude_request_id)
    recent = await session.scalar(recent_q)
    if recent is not None:
        return Eligibility(False, "frequency_limit")
    return Eligibility(True, channel=chosen)
