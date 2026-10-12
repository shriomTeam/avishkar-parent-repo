import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_core.features import Event, JobContext
from clinic_db.models.core import Appointment, Tenant, Transaction
from clinic_db.models.reactivation import Campaign, CampaignTarget
from clinic_engagement import enroll
from clinic_reactivation.rules import DEFAULT_LAPSED_DAYS, find_lapsed_patients

FEATURE_KEY = "reactivation"


async def default_lapsed_days(session: AsyncSession) -> int:
    tenant = await session.get(Tenant, current_tenant(session))
    return DEFAULT_LAPSED_DAYS.get(tenant.clinic_type, 120)


async def create_campaign(session: AsyncSession, *, name: str, lapsed_days: int) -> Campaign:
    campaign = Campaign(tenant_id=current_tenant(session), name=name, criteria={"lapsed_days": lapsed_days})
    session.add(campaign)
    await session.flush()
    for p in await find_lapsed_patients(session, lapsed_days=lapsed_days):
        session.add(
            CampaignTarget(
                tenant_id=campaign.tenant_id,
                campaign_id=campaign.id,
                patient_id=p.patient_id,
                days_lapsed=p.days_lapsed,
                lifetime_value_cents=p.lifetime_value_cents,
            )
        )
    return campaign


async def launch_campaign(session: AsyncSession, campaign: Campaign) -> int:
    if campaign.status != "draft":
        raise ValueError("campaign already launched")
    targets = (
        await session.scalars(
            select(CampaignTarget).where(CampaignTarget.campaign_id == campaign.id, CampaignTarget.status == "pending")
        )
    ).all()
    for t in targets:
        await enroll(
            session,
            sequence_key=campaign.sequence_key,
            owner_feature=FEATURE_KEY,
            patient_id=t.patient_id,
            owner_ref=t.id,
        )
        t.status = "contacted"
    campaign.status, campaign.launched_at = "running", datetime.now(UTC)
    return len(targets)


async def campaign_stats(session: AsyncSession, campaign_id: uuid.UUID) -> dict:
    by_status = dict(
        (
            await session.execute(
                select(CampaignTarget.status, func.count())
                .where(CampaignTarget.campaign_id == campaign_id)
                .group_by(CampaignTarget.status)
            )
        ).all()
    )
    booked_revenue = await session.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(CampaignTarget, CampaignTarget.booked_appointment_id == Transaction.appointment_id)
        .where(CampaignTarget.campaign_id == campaign_id)
    )
    dormant_value = await session.scalar(
        select(func.coalesce(func.sum(CampaignTarget.lifetime_value_cents), 0)).where(
            CampaignTarget.campaign_id == campaign_id
        )
    )
    return {
        "targets": sum(by_status.values()),
        "by_status": by_status,
        "booked": by_status.get("booked", 0),
        "booked_revenue_cents": int(booked_revenue or 0),
        "dormant_lifetime_value_cents": int(dormant_value or 0),
    }


async def on_appointment_booked(ctx: JobContext, event: Event) -> None:
    """Attribute the booking to the running campaign that contacted this patient."""
    target = await ctx.session.scalar(
        select(CampaignTarget)
        .join(Campaign, Campaign.id == CampaignTarget.campaign_id)
        .where(
            Campaign.status == "running",
            CampaignTarget.patient_id == uuid.UUID(event.payload["patient_id"]),
            CampaignTarget.status == "contacted",
        )
        .order_by(Campaign.launched_at.desc())
        .limit(1)
    )
    if target is None:
        return
    appointment = await ctx.session.get(Appointment, uuid.UUID(event.payload["appointment_id"]))
    target.status = "booked"
    target.booked_appointment_id = appointment.id if appointment else None
    target.booked_at = datetime.now(UTC)
