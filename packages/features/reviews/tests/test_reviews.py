import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select

from clinic_core.auth.database import create_database
from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import set_feature
from clinic_core.events import APPOINTMENT_COMPLETED, CONSENT_CHANGED
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


async def test_unknown_token_is_not_found():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        missing = await c.get("/public/reviews/not-a-real-token")
    assert missing.status_code == 404


async def test_one_clinic_cannot_read_another_clinics_request():
    first = await create_test_tenant(("reviews",))
    second = await create_test_tenant(("reviews",))
    await _ready_campaign(first)
    patient_id, appointment_id = await _patient(first)
    async with tenant_session(first) as s:
        await service.process_appointment_completed(s, _event(first, appointment_id, patient_id), now=NOW)
        request_id = await s.scalar(select(ReviewRequest.id))
    async with tenant_session(second) as s:
        assert await s.get(ReviewRequest, request_id) is None


async def test_second_submit_returns_the_existing_feedback():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, appointment_id = await _patient(tenant, name="Alex", phone="+15555550102")
    async with tenant_session(tenant) as s:
        await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)
        await service.dispatch_due(JobContext(tenant, s), {}, now=NOW)
        token = await s.scalar(select(ReviewRequest.public_token))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        first, second = await asyncio.gather(
            c.post(f"/public/reviews/{token}", json={"rating": 5, "comment": "Great"}),
            c.post(f"/public/reviews/{token}", json={"rating": 1, "comment": "Later"}),
        )
    assert first.status_code == 200 and second.status_code == 200
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(Feedback))).all()
    assert len(rows) == 1


async def test_consent_revoked_after_scheduling_cancels_the_request():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, appointment_id = await _patient(tenant)
    async with tenant_session(tenant) as s:
        await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)
        await service.on_consent_changed(
            JobContext(tenant, s),
            Event(
                id=2,
                tenant_id=tenant,
                type=CONSENT_CHANGED,
                payload={"patient_id": str(patient_id), "kind": "sms", "granted": False},
                created_at=NOW,
            ),
        )
        row = (await s.scalars(select(ReviewRequest))).one()
    assert row.status == "cancelled" and row.skip_reason == "opted_out"


async def test_second_visit_inside_the_frequency_window_is_skipped():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, first_appointment = await _patient(tenant)
    async with tenant_session(tenant) as s:
        second = Appointment(
            tenant_id=tenant, patient_id=patient_id, status="completed", starts_at=NOW - timedelta(minutes=30)
        )
        s.add(second)
        await s.flush()
        second_id = second.id
        await service.process_appointment_completed(s, _event(tenant, first_appointment, patient_id), now=NOW)
        await service.process_appointment_completed(s, _event(tenant, second_id, patient_id), now=NOW)
        rows = (await s.scalars(select(ReviewRequest))).all()
    assert sorted(row.status for row in rows) == ["scheduled", "skipped"]
    assert any(row.skip_reason == "frequency_limit" for row in rows)


async def test_front_desk_cannot_activate_and_activation_needs_a_google_link():
    tenant = await create_test_tenant(("reviews",))
    headers = {"X-Tenant-Id": str(tenant), "X-Staff-Role": "owner"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        created = await c.post("/campaigns", headers=headers, json={"name": "Post visit"})
        campaign_id = created.json()["id"]
        denied = await c.post(f"/campaigns/{campaign_id}/activate", headers={**headers, "X-Staff-Role": "front_desk"})
        blocked = await c.post(f"/campaigns/{campaign_id}/activate", headers=headers)
        bad_link = await c.post(
            "/integration/google",
            headers=headers,
            json={"listing_name": "ABC Dental", "review_url": "https://example.com/review"},
        )
        saved = await c.post(
            "/integration/google",
            headers=headers,
            json={"listing_name": "ABC Dental", "review_url": "https://g.page/r/abc/review"},
        )
        activated = await c.post(f"/campaigns/{campaign_id}/activate", headers=headers)
    assert created.status_code == 201
    assert denied.status_code == 403
    assert blocked.status_code == 409
    assert bad_link.status_code == 422
    assert saved.status_code == 200 and saved.json()["status"] == "connected"
    assert activated.status_code == 200 and activated.json()["status"] == "active"


async def test_public_link_stops_working_when_the_feature_is_removed():
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    patient_id, appointment_id = await _patient(tenant)
    async with tenant_session(tenant) as s:
        await service.process_appointment_completed(s, _event(tenant, appointment_id, patient_id), now=NOW)
        token = await s.scalar(select(ReviewRequest.public_token))
    async with system_session() as s:
        await set_feature(s, tenant, "reviews", enabled=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        closed = await c.get(f"/public/reviews/{token}")
    assert closed.status_code == 404


async def test_one_send_failure_does_not_block_the_rest_of_the_batch(monkeypatch):
    tenant = await create_test_tenant(("reviews",))
    await _ready_campaign(tenant)
    first_patient, first_appointment = await _patient(tenant, name="A", phone="+15555550110")
    second_patient, second_appointment = await _patient(tenant, name="B", phone="+15555550111")
    real_enroll = service.enroll
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider down")
        return await real_enroll(*args, **kwargs)

    monkeypatch.setattr(service, "enroll", flaky)
    async with tenant_session(tenant) as s:
        await service.process_appointment_completed(s, _event(tenant, first_appointment, first_patient), now=NOW)
        await service.process_appointment_completed(s, _event(tenant, second_appointment, second_patient), now=NOW)
        sent = await service.dispatch_due(JobContext(tenant, s), {}, now=NOW)
        rows = (await s.scalars(select(ReviewRequest))).all()
    assert sent == 1
    waiting = next(row for row in rows if row.status == "scheduled")
    sent_row = next(row for row in rows if row.status == "submitted")
    assert waiting.attempt_count == 1 and sent_row.submitted_at is not None

    async def always_down(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(service, "enroll", always_down)
    async with tenant_session(tenant) as s:
        request = await s.get(ReviewRequest, waiting.id)
        for _ in range(2):
            await service.dispatch_due(JobContext(tenant, s), {}, now=NOW)
        await s.refresh(request)
    assert request.status == "failed_permanent" and request.attempt_count == 3


@pytest.mark.parametrize(
    "url",
    [
        "https://search.google.com/local/writereview?placeid=abc",
        "https://maps.app.goo.gl/abc",
        "https://g.page/r/abc/review",
    ],
)
def test_google_review_hosts_are_accepted(url):
    assert google_profile.validate_review_url(url) == url


def test_other_https_urls_are_rejected():
    with pytest.raises(ValueError):
        google_profile.validate_review_url("https://example.com/review")
