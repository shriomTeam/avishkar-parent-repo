from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy import select

from clinic_core.auth.database import create_database
from clinic_core.database import tenant_session
from clinic_core.events import CONSENT_CHANGED
from clinic_core.features import Event, JobContext
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Appointment, Patient
from clinic_db.models.engagement import Enrollment
from clinic_db.models.reactivation import Campaign, CampaignTarget
from clinic_reactivation import service
from clinic_reactivation.router import router

app = FastAPI()
# This isolated router test intentionally exercises the explicit dev-header adapter.
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)


async def _lapsed_patient(s, tenant, name):
    p = Patient(tenant_id=tenant, first_name=name)
    s.add(p)
    await s.flush()
    s.add(
        Appointment(
            tenant_id=tenant, patient_id=p.id, status="completed", starts_at=datetime.now(UTC) - timedelta(days=300)
        )
    )
    return p


async def _draft_campaign(tenant, *names):
    async with tenant_session(tenant) as s:
        patients = [await _lapsed_patient(s, tenant, n) for n in names]
        campaign = await service.create_campaign(s, name="t", lapsed_days=120)
        await s.flush()
        return campaign.id, [p.id for p in patients]


def _consent_event(tenant, patient_id, granted):
    return Event(
        id=1,
        tenant_id=tenant,
        type=CONSENT_CHANGED,
        payload={"patient_id": str(patient_id), "kind": "sms", "granted": granted},
        created_at=datetime.now(UTC),
    )


async def test_launch_requires_owner_or_office_manager():
    tenant = await create_test_tenant()
    campaign_id, _ = await _draft_campaign(tenant, "A")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        h = {"X-Tenant-Id": str(tenant)}
        denied = await c.post(f"/campaigns/{campaign_id}/launch", headers={**h, "X-Staff-Role": "front_desk"})
        create_denied = await c.post("/campaigns", headers={**h, "X-Staff-Role": "front_desk"}, json={})
        ok = await c.post(f"/campaigns/{campaign_id}/launch", headers={**h, "X-Staff-Role": "owner"})
    assert denied.status_code == 403
    assert create_denied.status_code == 403
    assert ok.status_code == 200 and ok.json()["status"] == "running"


async def test_launch_skips_patient_who_booked_after_campaign_creation():
    tenant = await create_test_tenant()
    campaign_id, (rebooked_id, other_id) = await _draft_campaign(tenant, "Rebooked", "Other")
    async with tenant_session(tenant) as s:
        s.add(
            Appointment(
                tenant_id=tenant,
                patient_id=rebooked_id,
                status="booked",
                starts_at=datetime.now(UTC) + timedelta(days=3),
            )
        )
    async with tenant_session(tenant) as s:
        campaign = await s.get(Campaign, campaign_id)
        enrolled = await service.launch_campaign(s, campaign)
    async with tenant_session(tenant) as s:
        statuses = dict((await s.execute(select(CampaignTarget.patient_id, CampaignTarget.status))).all())
        enrolled_patients = set((await s.scalars(select(Enrollment.patient_id))).all())
    assert enrolled == 1
    assert statuses[rebooked_id] == "pending" and statuses[other_id] == "contacted"
    assert enrolled_patients == {other_id}


async def test_consent_withdrawn_opts_out_contacted_target_idempotently():
    tenant = await create_test_tenant()
    campaign_id, (patient_id,) = await _draft_campaign(tenant, "A")
    async with tenant_session(tenant) as s:
        await service.launch_campaign(s, await s.get(Campaign, campaign_id))

    async def fire(granted):
        async with tenant_session(tenant) as s:
            await service.on_consent_changed(JobContext(tenant, s), _consent_event(tenant, patient_id, granted))

    async def status():
        async with tenant_session(tenant) as s:
            return await s.scalar(select(CampaignTarget.status).where(CampaignTarget.patient_id == patient_id))

    await fire(True)
    assert await status() == "contacted"
    await fire(False)
    assert await status() == "opted_out"
    await fire(False)
    assert await status() == "opted_out"
