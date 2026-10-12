"""Who counts as "dormant". Reads only canonical core tables, so it works the same
whatever EMR or file the clinic's data came from."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.core import Appointment, AppointmentStatus, ClinicType, Patient, Transaction

# Typical rebooking cadence differs by clinic type (neurotoxin ~3-4 months, HRT monthly).
DEFAULT_LAPSED_DAYS = {ClinicType.MEDSPA: 120, ClinicType.WELLNESS: 90, ClinicType.HRT: 60}


@dataclass(frozen=True)
class LapsedPatient:
    patient_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    last_visit_at: datetime
    days_lapsed: int
    visits: int
    lifetime_value_cents: int


async def find_lapsed_patients(
    session: AsyncSession, *, lapsed_days: int, min_visits: int = 1, now: datetime | None = None
) -> list[LapsedPatient]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=lapsed_days)

    visits = (
        select(
            Appointment.patient_id,
            func.max(Appointment.starts_at).label("last_visit_at"),
            func.count().label("visits"),
        )
        .where(Appointment.status == AppointmentStatus.COMPLETED)
        .group_by(Appointment.patient_id)
        .subquery()
    )
    upcoming = (
        select(Appointment.patient_id)
        .where(Appointment.status == AppointmentStatus.BOOKED, Appointment.starts_at >= now)
        .subquery()
    )
    ltv = (
        select(Transaction.patient_id, func.coalesce(func.sum(Transaction.amount_cents), 0).label("ltv"))
        .group_by(Transaction.patient_id)
        .subquery()
    )
    stmt = (
        select(
            Patient.id,
            Patient.first_name,
            Patient.last_name,
            visits.c.last_visit_at,
            visits.c.visits,
            func.coalesce(ltv.c.ltv, 0),
        )
        .join(visits, visits.c.patient_id == Patient.id)
        .outerjoin(ltv, ltv.c.patient_id == Patient.id)
        .where(
            and_(visits.c.last_visit_at < cutoff, visits.c.visits >= min_visits),
            Patient.id.not_in(select(upcoming.c.patient_id)),
        )
        .order_by(func.coalesce(ltv.c.ltv, 0).desc())
    )
    return [
        LapsedPatient(
            patient_id=pid,
            first_name=first,
            last_name=last,
            last_visit_at=last_visit,
            days_lapsed=(now - last_visit).days,
            visits=n,
            lifetime_value_cents=int(value),
        )
        for pid, first, last, last_visit, n, value in (await session.execute(stmt)).all()
    ]
