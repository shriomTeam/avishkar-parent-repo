import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_core.database import current_tenant
from clinic_core.events import APPOINTMENT_COMPLETED, CONSENT_CHANGED
from clinic_core.features import Event, JobContext
from clinic_core.settings import get_settings
from clinic_db.models.core import Appointment, Patient, Tenant
from clinic_db.models.engagement import Enrollment
from clinic_db.models.reviews import Campaign, Feedback, FollowUpTask, ReviewRequest
from clinic_engagement import enroll
from clinic_reviews import eligibility
from clinic_reviews.constants import (
    EMAIL_SEQUENCE_KEY,
    FEATURE_KEY,
    GOOGLE_REVIEW_MIN,
    MAX_DISPATCH_ATTEMPTS,
    SMS_SEQUENCE_KEY,
)


def new_public_token() -> str:
    return secrets.token_urlsafe(24)


def review_link(token: str) -> str:
    return f"{get_settings().public_app_origin}/reviews/r/{token}"


async def process_appointment_completed(session: AsyncSession, event: Event, *, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    appointment = await session.get(Appointment, event.payload["appointment_id"])
    patient = await session.get(Patient, event.payload["patient_id"])
    tenant = await session.get(Tenant, current_tenant(session))
    if appointment is None or patient is None or tenant is None:
        return
    for campaign in await eligibility.applicable_campaigns(session, appointment):
        if await eligibility.already_processed(session, appointment.id, campaign.id):
            continue
        result = await eligibility.evaluate(
            session, tenant=tenant, campaign=campaign, appointment=appointment, patient=patient, now=now
        )
        request = ReviewRequest(
            tenant_id=tenant.id,
            campaign_id=campaign.id,
            appointment_id=appointment.id,
            patient_id=patient.id,
            public_token=new_public_token(),
            scheduled_at=now + timedelta(minutes=campaign.delay_minutes),
            channel=result.channel,
            status="scheduled" if result.ok else "skipped",
            skip_reason=None if result.ok else result.reason,
        )
        try:
            async with session.begin_nested():
                session.add(request)
                await session.flush()
        except IntegrityError:
            continue
        await audit(
            session,
            "reviews.eligibility",
            actor_type="system",
            entity_type="review_request",
            entity_id=request.id,
            details={"eligible": result.ok, "reason": result.reason, "channel": result.channel},
        )


async def dispatch_due(ctx: JobContext, _data: dict, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    due = (
        await ctx.session.scalars(
            select(ReviewRequest)
            .where(ReviewRequest.status == "scheduled", ReviewRequest.scheduled_at <= now)
            .order_by(ReviewRequest.scheduled_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
    ).all()
    sent = 0
    for request in due:
        try:
            async with ctx.session.begin_nested():
                queued = await _dispatch_one(ctx.session, request, now=now)
        except Exception as exc:
            await _note_dispatch_failure(ctx.session, request, now, exc)
            continue
        if queued:
            sent += 1
    return sent


async def _note_dispatch_failure(session: AsyncSession, request: ReviewRequest, now: datetime, exc: Exception) -> None:
    await session.refresh(request)
    request.attempt_count += 1
    request.claimed_at = now
    request.failure_reason = type(exc).__name__[:200]
    request.status = "failed_permanent" if request.attempt_count >= MAX_DISPATCH_ATTEMPTS else "scheduled"
    await session.flush()


async def _dispatch_one(session: AsyncSession, request: ReviewRequest, *, now: datetime) -> bool:
    request.status = "processing"
    request.claimed_at = now
    request.attempt_count += 1
    await session.flush()

    campaign = await session.get(Campaign, request.campaign_id)
    appointment = await session.get(Appointment, request.appointment_id)
    patient = await session.get(Patient, request.patient_id)
    tenant = await session.get(Tenant, current_tenant(session))
    if campaign is None or appointment is None or patient is None or tenant is None:
        request.status, request.failure_reason = "failed_permanent", "missing_records"
        return False

    result = await eligibility.evaluate(
        session,
        tenant=tenant,
        campaign=campaign,
        appointment=appointment,
        patient=patient,
        now=now,
        exclude_request_id=request.id,
    )
    if not result.ok:
        request.status, request.skip_reason, request.channel = "skipped", result.reason, result.channel
        return False

    existing = await session.scalar(
        select(Enrollment.id).where(Enrollment.owner_feature == FEATURE_KEY, Enrollment.owner_ref == request.id)
    )
    if existing is None:
        await enroll(
            session,
            sequence_key=EMAIL_SEQUENCE_KEY if result.channel == "email" else SMS_SEQUENCE_KEY,
            owner_feature=FEATURE_KEY,
            patient_id=patient.id,
            owner_ref=request.id,
            context={"review_request_link": review_link(request.public_token)},
            now=now,
        )

    request.channel = result.channel
    # submitted means the engagement sequence accepted the message. That sequence sends it.
    request.submitted_at = now
    request.status = "submitted"
    await audit(
        session,
        "reviews.submitted",
        actor_type="system",
        entity_type="review_request",
        entity_id=request.id,
        details={"channel": request.channel},
    )
    return True


async def on_appointment_completed(ctx: JobContext, event: Event) -> None:
    if event.type != APPOINTMENT_COMPLETED:
        return
    await process_appointment_completed(ctx.session, event)


async def on_consent_changed(ctx: JobContext, event: Event) -> None:
    if event.type != CONSENT_CHANGED or event.payload.get("granted"):
        return
    kind = event.payload.get("kind")
    patient_id = event.payload.get("patient_id")
    if not patient_id:
        return
    q = update(ReviewRequest).where(
        ReviewRequest.patient_id == uuid.UUID(str(patient_id)),
        ReviewRequest.status == "scheduled",
    )
    if kind in ("sms", "email"):
        q = q.where(ReviewRequest.channel == kind)
    await ctx.session.execute(q.values(status="cancelled", skip_reason="opted_out"))


async def submit_feedback(
    session: AsyncSession, request: ReviewRequest, *, rating: int, comment: str | None
) -> Feedback:
    existing = await session.scalar(select(Feedback).where(Feedback.request_id == request.id))
    if existing is not None:
        return existing
    feedback = Feedback(
        tenant_id=request.tenant_id,
        request_id=request.id,
        patient_id=request.patient_id,
        rating=rating,
        comment=comment or None,
        google_review_offered=rating >= GOOGLE_REVIEW_MIN,
    )
    try:
        async with session.begin_nested():
            session.add(feedback)
            request.status = "completed"
            await session.flush()
    except IntegrityError:
        session.expunge(feedback)
        existing = await session.scalar(select(Feedback).where(Feedback.request_id == request.id))
        if existing is None:
            raise
        return existing
    if rating < GOOGLE_REVIEW_MIN:
        session.add(
            FollowUpTask(
                tenant_id=request.tenant_id, feedback_id=feedback.id, rating=rating, reason="low_patient_rating"
            )
        )
    await audit(
        session,
        "reviews.feedback_submitted",
        actor_type="patient",
        actor_id=str(request.patient_id),
        entity_type="feedback",
        entity_id=feedback.id,
        details={"rating": rating},
    )
    return feedback


async def mark_google_clicked(session: AsyncSession, request: ReviewRequest) -> None:
    feedback = await session.scalar(select(Feedback).where(Feedback.request_id == request.id))
    if feedback is None or not feedback.google_review_offered or feedback.google_review_clicked_at is not None:
        return
    feedback.google_review_clicked_at = datetime.now(UTC)


async def campaign_stats(session: AsyncSession, campaign_id) -> dict:
    by_status = dict(
        (
            await session.execute(
                select(ReviewRequest.status, func.count())
                .where(ReviewRequest.campaign_id == campaign_id)
                .group_by(ReviewRequest.status)
            )
        ).all()
    )
    ratings = await session.scalar(
        select(func.count())
        .select_from(Feedback)
        .join(ReviewRequest, ReviewRequest.id == Feedback.request_id)
        .where(ReviewRequest.campaign_id == campaign_id)
    )
    follow_ups = await session.scalar(
        select(func.count())
        .select_from(FollowUpTask)
        .join(Feedback, Feedback.id == FollowUpTask.feedback_id)
        .join(ReviewRequest, ReviewRequest.id == Feedback.request_id)
        .where(ReviewRequest.campaign_id == campaign_id, FollowUpTask.status == "pending")
    )
    return {
        "requests": sum(by_status.values()),
        "by_status": by_status,
        "ratings_submitted": int(ratings or 0),
        "pending_follow_ups": int(follow_ups or 0),
    }
