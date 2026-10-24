"""Completing a visit is a staff action and only applies after the visit has started."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.core import Appointment, Patient
from clinic_db.models.ops import AuditLog


async def _visit(tenant, *, starts_at):
    async with tenant_session(tenant) as s:
        patient = Patient(tenant_id=tenant, first_name="Mina")
        s.add(patient)
        await s.flush()
        appointment = Appointment(tenant_id=tenant, patient_id=patient.id, status="booked", starts_at=starts_at)
        s.add(appointment)
        await s.flush()
        return appointment.id


async def test_complete_requires_a_started_visit_and_writes_an_audit(make_tenant, client):
    tenant = await make_tenant()
    future_id = await _visit(tenant, starts_at=datetime.now(UTC) + timedelta(days=1))
    past_id = await _visit(tenant, starts_at=datetime.now(UTC) - timedelta(hours=1))
    headers = {"X-Tenant-Id": str(tenant)}

    future = await client.post(f"/appointments/{future_id}/complete", headers=headers)
    denied = await client.post(f"/appointments/{past_id}/complete", headers={**headers, "X-Staff-Role": "consultant"})
    completed = await client.post(
        f"/appointments/{past_id}/complete", headers={**headers, "X-Staff-Role": "front_desk"}
    )

    assert future.status_code == 409
    assert denied.status_code == 403
    assert completed.status_code == 200 and completed.json()["status"] == "completed"
    async with tenant_session(tenant) as s:
        entry = await s.scalar(select(AuditLog).where(AuditLog.action == "appointment.completed"))
    assert entry is not None and entry.entity_id == past_id and entry.actor_type == "staff"
