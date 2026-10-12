from datetime import UTC, datetime, timedelta

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Appointment, Patient, Transaction
from clinic_reactivation.rules import find_lapsed_patients

NOW = datetime(2026, 6, 1, 15, tzinfo=UTC)


async def _patient(s, tenant, name, *, last_visit_days_ago, upcoming=False, spend=0):
    p = Patient(tenant_id=tenant, first_name=name)
    s.add(p)
    await s.flush()
    visit = Appointment(
        tenant_id=tenant, patient_id=p.id, status="completed", starts_at=NOW - timedelta(days=last_visit_days_ago)
    )
    s.add(visit)
    if upcoming:
        s.add(Appointment(tenant_id=tenant, patient_id=p.id, status="booked", starts_at=NOW + timedelta(days=7)))
    if spend:
        s.add(Transaction(tenant_id=tenant, patient_id=p.id, amount_cents=spend, occurred_at=visit.starts_at))
    return p


async def test_lapsed_means_old_last_visit_and_nothing_booked():
    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        await _patient(s, tenant, "Regular", last_visit_days_ago=30)
        await _patient(s, tenant, "AlreadyRebooked", last_visit_days_ago=200, upcoming=True)
        await _patient(s, tenant, "Small", last_visit_days_ago=200, spend=10_000)
        await _patient(s, tenant, "Big", last_visit_days_ago=400, spend=90_000)

        lapsed = await find_lapsed_patients(s, lapsed_days=120, now=NOW)

    assert [p.first_name for p in lapsed] == ["Big", "Small"]  # highest lifetime value first
    assert lapsed[0].days_lapsed == 400 and lapsed[0].lifetime_value_cents == 90_000
