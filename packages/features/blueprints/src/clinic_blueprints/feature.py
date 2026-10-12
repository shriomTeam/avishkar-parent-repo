"""Patient Blueprint Report: the clinic's top three buying profiles.

v1 is a transparent heuristic (age band x gender x primary service category,
ranked by revenue) so the report is explainable to a clinic owner. The segment
logic can grow into proper clustering without changing the API.
"""

from collections import defaultdict
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import get_session
from clinic_core.features import Feature, NavItem
from clinic_db.models.core import Patient, Service, Transaction

router = APIRouter(tags=["blueprints"])


class Profile(BaseModel):
    label: str
    age_band: str
    gender: str
    primary_category: str
    patients: int
    share_of_revenue: float
    revenue_cents: int
    avg_revenue_per_patient_cents: int
    avg_purchases: float


class Report(BaseModel):
    generated_at: datetime
    patients_analyzed: int
    total_revenue_cents: int
    profiles: list[Profile]


def _age_band(dob: date | None, today: date) -> str:
    if dob is None:
        return "unknown age"
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    for upper, band in ((25, "18-24"), (35, "25-34"), (45, "35-44"), (55, "45-54"), (65, "55-64")):
        if age < upper:
            return band
    return "65+"


@router.get("/report", response_model=Report)
async def report(top: int = 3, session: AsyncSession = Depends(get_session)) -> Report:
    rows = (
        await session.execute(
            select(
                Patient.id,
                Patient.date_of_birth,
                Patient.gender,
                func.coalesce(Service.category, Service.name, "uncategorised"),
                func.sum(Transaction.amount_cents),
                func.count(),
            )
            .join(Transaction, Transaction.patient_id == Patient.id)
            .outerjoin(Service, Service.id == Transaction.service_id)
            .where(Transaction.amount_cents > 0)
            .group_by(Patient.id, Patient.date_of_birth, Patient.gender, Service.category, Service.name)
        )
    ).all()

    today = datetime.now(UTC).date()
    per_patient: dict = {}
    for pid, dob, gender, category, revenue, count in rows:
        p = per_patient.setdefault(
            pid, {"dob": dob, "gender": gender, "revenue": 0, "count": 0, "cats": defaultdict(int)}
        )
        p["revenue"] += revenue
        p["count"] += count
        p["cats"][category] += revenue

    segments: dict[tuple[str, str, str], dict] = defaultdict(lambda: {"patients": 0, "revenue": 0, "count": 0})
    for p in per_patient.values():
        key = (_age_band(p["dob"], today), (p["gender"] or "unknown").lower(), max(p["cats"], key=p["cats"].get))
        seg = segments[key]
        seg["patients"] += 1
        seg["revenue"] += p["revenue"]
        seg["count"] += p["count"]

    total = sum(s["revenue"] for s in segments.values()) or 1
    ranked = sorted(segments.items(), key=lambda kv: kv[1]["revenue"], reverse=True)[:top]
    return Report(
        generated_at=datetime.now(UTC),
        patients_analyzed=len(per_patient),
        total_revenue_cents=int(total if per_patient else 0),
        profiles=[
            Profile(
                label=f"{gender.title()}, {band}, buys {cat}",
                age_band=band,
                gender=gender,
                primary_category=cat,
                patients=s["patients"],
                share_of_revenue=round(s["revenue"] / total, 3),
                revenue_cents=int(s["revenue"]),
                avg_revenue_per_patient_cents=int(s["revenue"] / s["patients"]),
                avg_purchases=round(s["count"] / s["patients"], 1),
            )
            for (band, gender, cat), s in ranked
        ],
    )


feature = Feature(
    key="blueprints",
    name="Patient Blueprints",
    description="Top buying profiles from the clinic's own records, for targeting and cross-sell.",
    router=router,
    nav=[NavItem(label="Patient Blueprints", path="/blueprints", roles=("owner", "consultant", "office_manager"))],
    trial_eligible=True,
)
