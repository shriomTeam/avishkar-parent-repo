import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import get_session, require_role
from clinic_db.models.core import StaffRole
from clinic_db.models.reactivation import Campaign
from clinic_reactivation import service
from clinic_reactivation.api.results import router as results_router
from clinic_reactivation.api.runs import router as runs_router
from clinic_reactivation.api.settings import router as settings_router
from clinic_reactivation.rules import find_lapsed_patients

router = APIRouter(tags=["reactivation"])
router.include_router(settings_router)
router.include_router(results_router)
router.include_router(runs_router)


class LapsedPatientOut(BaseModel):
    patient_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    last_visit_at: datetime
    days_lapsed: int
    visits: int
    lifetime_value_cents: int


class PreviewOut(BaseModel):
    lapsed_days: int
    dormant_patients: int
    dormant_lifetime_value_cents: int
    top: list[LapsedPatientOut]


class CampaignIn(BaseModel):
    name: str = "Dormant Revenue Finder"
    lapsed_days: int | None = Field(default=None, ge=14, le=3650)


class CampaignStats(BaseModel):
    targets: int
    by_status: dict[str, int]
    booked: int
    booked_revenue_cents: int
    dormant_lifetime_value_cents: int


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    criteria: dict
    launched_at: datetime | None
    stats: CampaignStats


@router.get("/preview", response_model=PreviewOut)
async def preview(lapsed_days: int | None = None, session: AsyncSession = Depends(get_session)) -> PreviewOut:
    """The lead-magnet headline: how many patients, worth how much, have gone quiet."""
    days = lapsed_days or await service.default_lapsed_days(session)
    lapsed = await find_lapsed_patients(session, lapsed_days=days)
    return PreviewOut(
        lapsed_days=days,
        dormant_patients=len(lapsed),
        dormant_lifetime_value_cents=sum(p.lifetime_value_cents for p in lapsed),
        top=[LapsedPatientOut(**p.__dict__) for p in lapsed[:20]],
    )


async def _out(session: AsyncSession, c: Campaign) -> CampaignOut:
    return CampaignOut(
        id=c.id,
        name=c.name,
        status=c.status,
        criteria=c.criteria,
        launched_at=c.launched_at,
        stats=CampaignStats(**await service.campaign_stats(session, c.id)),
    )


MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


@router.post("/campaigns", response_model=CampaignOut, status_code=201, dependencies=MANAGERS)
async def create_campaign(body: CampaignIn, session: AsyncSession = Depends(get_session)) -> CampaignOut:
    days = body.lapsed_days or await service.default_lapsed_days(session)
    campaign = await service.create_campaign(session, name=body.name, lapsed_days=days)
    await session.flush()
    return await _out(session, campaign)


@router.get("/campaigns", response_model=list[CampaignOut])
async def list_campaigns(session: AsyncSession = Depends(get_session)) -> list[CampaignOut]:
    campaigns = (await session.scalars(select(Campaign).order_by(Campaign.created_at.desc()))).all()
    return [await _out(session, c) for c in campaigns]


@router.post("/campaigns/{campaign_id}/launch", response_model=CampaignOut, dependencies=MANAGERS)
async def launch(campaign_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> CampaignOut:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "campaign not found")
    try:
        await service.launch_campaign(session, campaign)
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    await session.flush()
    return await _out(session, campaign)
