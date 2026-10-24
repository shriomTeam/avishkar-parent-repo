import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import get_session, require_role
from clinic_core.database import current_tenant
from clinic_db.models.core import StaffRole
from clinic_db.models.reviews import Campaign, FollowUpTask
from clinic_reviews import google_profile, service

router = APIRouter(tags=["reviews"])
MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


class CampaignIn(BaseModel):
    name: str = "Post Appointment Review"
    delay_minutes: int = Field(default=120, ge=0, le=10080)
    channels: list[str] = Field(default_factory=lambda: ["sms"])
    fallback_enabled: bool = True
    included_service_ids: list[uuid.UUID] = Field(default_factory=list)
    excluded_service_ids: list[uuid.UUID] = Field(default_factory=list)
    frequency_days: int = Field(default=30, ge=1, le=365)


class CampaignStats(BaseModel):
    requests: int
    by_status: dict[str, int]
    ratings_submitted: int
    pending_follow_ups: int


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    delay_minutes: int
    channels: list
    frequency_days: int
    activated_at: datetime | None
    stats: CampaignStats


class IntegrationOut(BaseModel):
    listing_name: str | None
    google_review_url: str | None
    status: str
    last_validated_at: datetime | None


class ConnectGoogleIn(BaseModel):
    listing_name: str = Field(min_length=1, max_length=200)
    review_url: str = Field(min_length=8, max_length=500)


class FollowUpItem(BaseModel):
    id: uuid.UUID
    rating: int
    reason: str
    status: str


class OverviewOut(BaseModel):
    integration: IntegrationOut
    campaigns: list[CampaignOut]
    pending_follow_ups: list[FollowUpItem]


class FollowUpOut(BaseModel):
    id: uuid.UUID
    status: str


async def _campaign_out(session: AsyncSession, campaign: Campaign) -> CampaignOut:
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        status=campaign.status,
        delay_minutes=campaign.delay_minutes,
        channels=list(campaign.channels or []),
        frequency_days=campaign.frequency_days,
        activated_at=campaign.activated_at,
        stats=CampaignStats(**await service.campaign_stats(session, campaign.id)),
    )


@router.get("/status")
async def status() -> dict:
    return {"feature": "reviews", "status": "ready"}


@router.get("/overview", response_model=OverviewOut)
async def overview(session: AsyncSession = Depends(get_session)) -> OverviewOut:
    integration = await google_profile.get_or_create(session)
    campaigns = (await session.scalars(select(Campaign).order_by(Campaign.created_at.desc()))).all()
    tasks = (
        await session.scalars(
            select(FollowUpTask).where(FollowUpTask.status == "pending").order_by(FollowUpTask.created_at.desc())
        )
    ).all()
    return OverviewOut(
        integration=IntegrationOut(
            listing_name=integration.listing_name,
            google_review_url=integration.google_review_url,
            status=integration.status,
            last_validated_at=integration.last_validated_at,
        ),
        campaigns=[await _campaign_out(session, c) for c in campaigns],
        pending_follow_ups=[FollowUpItem(id=t.id, rating=t.rating, reason=t.reason, status=t.status) for t in tasks],
    )


@router.post("/integration/google", response_model=IntegrationOut, dependencies=MANAGERS)
async def connect_google(body: ConnectGoogleIn, session: AsyncSession = Depends(get_session)) -> IntegrationOut:
    try:
        url = google_profile.validate_review_url(body.review_url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    row = await google_profile.connect(session, listing_name=body.listing_name.strip(), review_url=url)
    return IntegrationOut(
        listing_name=row.listing_name,
        google_review_url=row.google_review_url,
        status=row.status,
        last_validated_at=row.last_validated_at,
    )


@router.post("/campaigns", response_model=CampaignOut, status_code=201, dependencies=MANAGERS)
async def create_campaign(body: CampaignIn, session: AsyncSession = Depends(get_session)) -> CampaignOut:
    channels = [c for c in body.channels if c in ("sms", "email")]
    if not channels:
        raise HTTPException(422, "at least one channel is required")
    campaign = Campaign(
        tenant_id=current_tenant(session),
        name=body.name,
        delay_minutes=body.delay_minutes,
        channels=channels,
        fallback_enabled=body.fallback_enabled,
        included_service_ids=[str(i) for i in body.included_service_ids],
        excluded_service_ids=[str(i) for i in body.excluded_service_ids],
        frequency_days=body.frequency_days,
    )
    session.add(campaign)
    await session.flush()
    return await _campaign_out(session, campaign)


@router.post("/campaigns/{campaign_id}/activate", response_model=CampaignOut, dependencies=MANAGERS)
async def activate_campaign(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> CampaignOut:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    integration = await google_profile.get_or_create(session)
    if integration.status != "connected":
        raise HTTPException(409, "save a Google Business Profile review link before activating")
    if campaign.status != "active":
        campaign.status = "active"
        campaign.activated_at = datetime.now(UTC)
    return await _campaign_out(session, campaign)


@router.post("/follow-ups/{task_id}/resolve", response_model=FollowUpOut, dependencies=MANAGERS)
async def resolve_follow_up(task_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> FollowUpOut:
    task = await session.get(FollowUpTask, task_id)
    if task is None:
        raise HTTPException(404, "follow-up not found")
    task.status = "resolved"
    task.resolved_at = datetime.now(UTC)
    return FollowUpOut(id=task.id, status=task.status)
