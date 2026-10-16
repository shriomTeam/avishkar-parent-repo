from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Appointment, Patient
from clinic_db.models.reactivation import Campaign, CampaignTarget, Run, RunPatient, RunType
from clinic_reactivation import service


async def _run_with_results(tenant):
    """A completed run with one patient row, one type row and one campaign linked to it."""
    async with tenant_session(tenant) as s:
        patient = Patient(tenant_id=tenant, first_name="A")
        run = Run(tenant_id=tenant, trigger="manual", status="completed", settings_version=0, settings={})
        s.add_all([patient, run])
        await s.flush()
        s.add(
            RunPatient(
                tenant_id=tenant,
                run_id=run.id,
                patient_id=patient.id,
                status="dormant",
                primary_type="one_and_done",
                visit_count=1,
                total_spend_cents=5000,
            )
        )
        s.add(
            RunType(
                tenant_id=tenant,
                run_id=run.id,
                type_key="one_and_done",
                patient_count=1,
                basis_total_cents=5000,
                rate_low=0.08,
                rate_high=0.15,
                rate_source="assumed",
                revenue_low_cents=400,
                revenue_high_cents=750,
                revenue_kind="new",
            )
        )
        campaign = Campaign(tenant_id=tenant, name="c", criteria={}, run_id=run.id, type_key="one_and_done")
        s.add(campaign)
        await s.flush()
        return run.id, campaign.id


async def _delete_run(tenant, run_id):
    async with tenant_session(tenant) as s:
        await s.delete(await s.get(Run, run_id))


async def test_deleting_a_run_cascades_to_its_patients_and_types():
    t = await create_test_tenant()
    run_id, _ = await _run_with_results(t)
    await _delete_run(t, run_id)
    async with tenant_session(t) as s:
        assert await s.scalar(select(func.count()).select_from(RunPatient)) == 0
        assert await s.scalar(select(func.count()).select_from(RunType)) == 0


async def test_deleting_a_run_keeps_its_campaigns_with_run_id_null():
    t = await create_test_tenant()
    run_id, campaign_id = await _run_with_results(t)
    await _delete_run(t, run_id)
    async with tenant_session(t) as s:
        campaign = await s.get(Campaign, campaign_id)
        assert campaign is not None
        assert campaign.run_id is None
        assert campaign.type_key == "one_and_done"  # informational only, untouched


async def test_campaign_with_new_columns_empty_still_works():
    t = await create_test_tenant()
    async with tenant_session(t) as s:
        p = Patient(tenant_id=t, first_name="Lapsed")
        s.add(p)
        await s.flush()
        s.add(
            Appointment(
                tenant_id=t, patient_id=p.id, status="completed", starts_at=datetime.now(UTC) - timedelta(days=300)
            )
        )
        campaign = await service.create_campaign(s, name="plain", lapsed_days=120)
        await s.flush()
        campaign_id = campaign.id
    async with tenant_session(t) as s:
        campaign = await s.get(Campaign, campaign_id)
        assert (campaign.run_id, campaign.type_key, campaign.category) == (None, None, None)
        assert (campaign.audience, campaign.schedule, campaign.content) == (None, None, None)
        assert await service.launch_campaign(s, campaign) == 1
        stats = await service.campaign_stats(s, campaign_id)
    assert stats["by_status"] == {"contacted": 1}


async def test_campaign_stores_free_form_customization_unchanged():
    t = await create_test_tenant()
    audience = {"any": ["shape", {"nested": True}]}
    schedule = {"whenever": "we like"}
    content = {"messages": [{"text": "hi"}]}
    async with tenant_session(t) as s:
        c = Campaign(
            tenant_id=t,
            name="c",
            criteria={},
            category="winter promo",
            audience=audience,
            schedule=schedule,
            content=content,
        )
        s.add(c)
        await s.flush()
        campaign_id = c.id
    async with tenant_session(t) as s:
        c = await s.get(Campaign, campaign_id)
        assert (c.category, c.audience, c.schedule, c.content) == ("winter promo", audience, schedule, content)
        assert await s.scalar(select(func.count()).select_from(CampaignTarget)) == 0
