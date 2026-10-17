from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.events import APPOINTMENT_COMPLETED
from clinic_core.features import Event, JobContext
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Appointment, Consent, Patient
from clinic_db.models.engagement import Enrollment
from clinic_db.models.reviews import Campaign, Feedback, FollowUpTask, ReviewRequest
from clinic_reviews import google_profile, service
from clinic_reviews.public import router as public_router
from clinic_reviews.router import router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)
app.include_router(public_router, prefix="/public/reviews")

NOW = datetime(2026, 10, 8, 14, tzinfo=UTC)
GOOGLE = "https://search.google.com/local/writereview?placeid=abc-dental"


async def _ready_campaign(tenant, *, delay_minutes=0):
    async with tenant_session(tenant) as s:
        await google_profile.connect(s, listing_name="ABC Dental", review_url=GOOGLE)
        campaign = Campaign(
            tenant_id=tenant,
            name="Post Appointment Review",
            status="active",
            delay_minutes=delay_minutes,
            channels=["sms"],
            frequency_days=30,
            activated_at=NOW,
        )
        s.add(campaign)
        await s.flush()
        return campaign.id


async def _patient(tenant, name="Mike", phone="+15555550100"):
    async with tenant_session(tenant) as s:
        patient = Patient(tenant_id=tenant, first_name=name, phone=phone)
        s.add(patient)
        await s.flush()
        s.add(Consent(tenant_id=tenant, patient_id=patient.id, kind="sms", granted=True))
        appointment = Appointment(
            tenant_id=tenant, patient_id=patient.id, status="completed", starts_at=NOW - timedelta(hours=1)
        )
        s.add(appointment)
        await s.flush()
        return patient.id, appointment.id


def _event(tenant, appointment_id, patient_id):
    return Event(
        id=1,
        tenant_id=tenant,
        type=APPOINTMENT_COMPLETED,
        payload={"appointment_id": str(appointment_id), "patient_id": str(patient_id)},
        created_at=NOW,
    )


async def test_completed_visit_schedules_one_request_and_duplicate_is_ignored():
    tenant = await create_test_tenant(("reviews",))
    campaign_id = await _ready_campaign(tenant, delay_minutes=120)
    patient_id, appointment_id = await _patient(tenant)

    async def run():
        async with tenant_session(tenant) as s:
            await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)

    await run()
    await run()
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(ReviewRequest))).all()
    assert len(rows) == 1
    assert rows[0].campaign_id == campaign_id
    assert rows[0].status == "scheduled"
    assert rows[0].scheduled_at == NOW + timedelta(hours=2)


async def test_dispatch_sends_feedback_link_and_rating_branch():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, appointment_id = await _patient(tenant)
    async with tenant_session(tenant) as s:
        await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)
        sent = await service.dispatch_due(JobContext(tenant, s), {}, now=NOW)
        token = await s.scalar(select(ReviewRequest.public_token))
        enrolled = await s.scalar(select(func.count()).select_from(Enrollment))
    assert sent == 1 and enrolled == 1

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        low = await c.post(f"/public/reviews/{token}", json={"rating": 2, "comment": "Long wait"})
    assert low.status_code == 200
    assert low.json()["next_step"] == "thanks"
    assert low.json()["google_review_url"] is None
    async with tenant_session(tenant) as s:
        offered = await s.scalar(select(Feedback.google_review_offered))
        follow_ups = await s.scalar(select(func.count()).select_from(FollowUpTask))
    assert offered is False and follow_ups == 1


async def test_high_rating_offers_google_review_link():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, appointment_id = await _patient(tenant, name="Sarah", phone="+15555550101")
    async with tenant_session(tenant) as s:
        await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)
        await service.dispatch_due(JobContext(tenant, s), {}, now=NOW)
        token = await s.scalar(select(ReviewRequest.public_token))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        high = await c.post(f"/public/reviews/{token}", json={"rating": 5})
        again = await c.get(f"/public/reviews/{token}")
        click = await c.post(f"/public/reviews/{token}/google-click")
    assert high.json()["next_step"] == "google_review"
    assert high.json()["google_review_url"] == GOOGLE
    assert again.json()["google_review_url"] == GOOGLE
    assert click.status_code == 200
    async with tenant_session(tenant) as s:
        clicked = await s.scalar(select(Feedback.google_review_clicked_at))
        follow_ups = await s.scalar(select(func.count()).select_from(FollowUpTask))
    assert clicked is not None and follow_ups == 0


async def test_opted_out_patient_is_skipped():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, appointment_id = await _patient(tenant)
    async with tenant_session(tenant) as s:
        s.add(
            Consent(
                tenant_id=tenant,
                patient_id=patient_id,
                kind="sms",
                granted=False,
                recorded_at=datetime.now(UTC),
            )
        )
        await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)
        row = (await s.scalars(select(ReviewRequest))).one()
    assert row.status == "skipped" and row.skip_reason == "opted_out"
