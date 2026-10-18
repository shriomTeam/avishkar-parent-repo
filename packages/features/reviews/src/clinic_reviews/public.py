from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from clinic_core.database import system_session, tenant_session
from clinic_db.models.core import Tenant
from clinic_db.models.reviews import Feedback, Integration, ReviewRequest
from clinic_reviews import service

router = APIRouter(tags=["reviews-public"])


class PublicFeedbackOut(BaseModel):
    practice_name: str
    rating: int | None
    comment: str | None
    submitted: bool
    next_step: str
    google_review_url: str | None


class PublicFeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=4000)


async def _ids_for_token(token: str) -> tuple:
    async with system_session() as session:
        row = (
            await session.execute(
                select(ReviewRequest.tenant_id, ReviewRequest.id).where(ReviewRequest.public_token == token)
            )
        ).first()
        if row is None:
            raise HTTPException(404, "request not found")
        return row.tenant_id, row.id


async def _payload(session, request: ReviewRequest, tenant: Tenant) -> PublicFeedbackOut:
    feedback = await session.scalar(select(Feedback).where(Feedback.request_id == request.id))
    integration = await session.scalar(select(Integration))
    offer_google = bool(feedback and feedback.google_review_offered and integration and integration.google_review_url)
    return PublicFeedbackOut(
        practice_name=tenant.name,
        rating=feedback.rating if feedback else None,
        comment=feedback.comment if feedback else None,
        submitted=feedback is not None,
        next_step="google_review" if offer_google else "thanks" if feedback else "form",
        google_review_url=integration.google_review_url if offer_google else None,
    )


@router.get("/{token}", response_model=PublicFeedbackOut)
async def get_feedback_page(token: str) -> PublicFeedbackOut:
    tenant_id, request_id = await _ids_for_token(token)
    async with tenant_session(tenant_id) as session:
        request = await session.get(ReviewRequest, request_id)
        tenant = await session.get(Tenant, tenant_id)
        if request is None or tenant is None:
            raise HTTPException(404, "request not found")
        return await _payload(session, request, tenant)


@router.post("/{token}", response_model=PublicFeedbackOut)
async def submit_feedback_page(token: str, body: PublicFeedbackIn) -> PublicFeedbackOut:
    tenant_id, request_id = await _ids_for_token(token)
    async with tenant_session(tenant_id) as session:
        request = await session.get(ReviewRequest, request_id)
        tenant = await session.get(Tenant, tenant_id)
        if request is None or tenant is None or request.status in ("skipped", "cancelled"):
            raise HTTPException(404, "request not found")
        await service.submit_feedback(session, request, rating=body.rating, comment=body.comment)
        return await _payload(session, request, tenant)


@router.post("/{token}/google-click", response_model=PublicFeedbackOut)
async def google_click(token: str) -> PublicFeedbackOut:
    tenant_id, request_id = await _ids_for_token(token)
    async with tenant_session(tenant_id) as session:
        request = await session.get(ReviewRequest, request_id)
        tenant = await session.get(Tenant, tenant_id)
        feedback = await session.scalar(select(Feedback).where(Feedback.request_id == request_id)) if request else None
        if request is None or tenant is None or feedback is None or not feedback.google_review_offered:
            raise HTTPException(404, "request not found")
        await service.mark_google_clicked(session, request)
        return await _payload(session, request, tenant)
