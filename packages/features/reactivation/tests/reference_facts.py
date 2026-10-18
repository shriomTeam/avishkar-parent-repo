"""An independent reference for ``facts.load_facts``, written from docs/analysis-engine-spec.md
(sections 4.1 to 4.5, 4.11) and docs/data-contract.md, over raw rows in plain Python.

It shares no code with the SQL or with ``analysis/facts.py``: different structure on purpose
(loops over raw rows, sets and dicts), so a disagreement means a bug in one of them.
"""

import json
import uuid
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.core import (
    Appointment,
    Consent,
    Membership,
    Patient,
    Provider,
    Service,
    Staff,
    Tenant,
    Transaction,
)

KNOWN_APPOINTMENT_STATUSES = {"completed", "booked", "cancelled", "no_show"}
KNOWN_MEMBERSHIP_STATUSES = {"active", "cancelled", "lapsed", "expired"}
TICKET_KINDS = {"service", "product"}


async def read_rows(session: AsyncSession) -> dict[str, list]:
    async def all_of(model):
        return list((await session.scalars(select(model))).all())

    return {
        "patients": await all_of(Patient),
        "appointments": await all_of(Appointment),
        "transactions": await all_of(Transaction),
        "services": await all_of(Service),
        "providers": await all_of(Provider),
        "staff": await all_of(Staff),
        "memberships": await all_of(Membership),
        "consents": await all_of(Consent),
        "tenants": await all_of(Tenant),
    }


def _flag(value: Any) -> str:
    if value is None:
        return "absent"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return {1: "true", 0: "false"}.get(value, "unparsable")
    if isinstance(value, str):
        t = value.strip().lower()
        if t == "":
            return "absent"
        if t in ("true", "yes", "y", "1"):
            return "true"
        if t in ("false", "no", "n", "0"):
            return "false"
    return "unparsable"


def _quote(value: Any) -> tuple[int | None, bool]:
    if value is None:
        return None, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, int):
        return (value, False) if value >= 0 else (None, True)
    if isinstance(value, str) and value.isascii() and value.isdigit() and 1 <= len(value) <= 12:
        return int(value), False
    return None, True


def _half_up(numerator: int, denominator: int) -> int:
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def reference_facts(
    rows: dict[str, list], now: datetime, tz_name: str, *, cap: int = 200, window: int = 60, cohort_min: int = 20
) -> dict[uuid.UUID, dict[str, Any]]:
    tz = ZoneInfo(tz_name)
    today = now.astimezone(tz).date()

    def day_of(moment: datetime) -> date:
        return moment.astimezone(tz).date()

    services = {s.id: s for s in rows["services"]}
    providers = {p.id: p for p in rows["providers"]}
    staff = {s.id: s for s in rows["staff"]}
    appt_by_id = {a.id: a for a in rows["appointments"]}
    tenant = rows["tenants"][0]
    opt_in_required = (
        bool(tenant.settings["sms_requires_explicit_opt_in"])
        if ("sms_requires_explicit_opt_in" in tenant.settings)
        else True
    )

    def is_consult(a) -> bool:
        s = services.get(a.service_id)
        return bool(s and s.category and s.category.strip().lower() == "consult")

    by_patient: dict[uuid.UUID, dict[str, list]] = {}
    for p in rows["patients"]:
        by_patient[p.id] = {"appts": [], "txns": [], "memb": [], "cons": []}
    for a in sorted(rows["appointments"], key=lambda r: r.id):
        by_patient[a.patient_id]["appts"].append(a)
    for t in rows["transactions"]:
        if t.patient_id is not None:
            by_patient[t.patient_id]["txns"].append(t)
    for m in rows["memberships"]:
        by_patient[m.patient_id]["memb"].append(m)
    for c in rows["consents"]:
        by_patient[c.patient_id]["cons"].append(c)

    # a transaction is an outlier above $5,000 and above 50 times the practice median of positive amounts
    positives = sorted(t.amount_cents for t in rows["transactions"] if t.amount_cents > 0)
    median = None
    if positives:
        mid = len(positives) // 2
        median = Fraction(positives[mid]) if len(positives) % 2 else Fraction(positives[mid - 1] + positives[mid], 2)

    out: dict[uuid.UUID, dict[str, Any]] = {}
    for p in rows["patients"]:
        mine = by_patient[p.id]
        seen: set = set()
        real = []  # appointments after dropping exact duplicates
        duplicates = 0
        for a in mine["appts"]:
            key = (a.starts_at, a.service_id, a.status)
            if key in seen:
                duplicates += 1
            else:
                seen.add(key)
                real.append(a)

        visits = [a for a in real if a.status == "completed" and a.starts_at <= now]
        days: dict[date, list] = {}
        for a in visits:
            days.setdefault(day_of(a.starts_at), []).append(a)
        ordered_days = sorted(days)
        kept = ordered_days[-cap:] if cap else ordered_days

        # usual service and provider, counted over visit days
        svc_days: dict[uuid.UUID, set] = {}
        prov_days: dict[uuid.UUID, set] = {}
        for d, appts in days.items():
            for a in appts:
                if a.service_id is not None:
                    svc_days.setdefault(a.service_id, set()).add(d)
                if a.provider_id is not None:
                    prov_days.setdefault(a.provider_id, set()).add(d)

        def pick(table: dict[uuid.UUID, set]) -> uuid.UUID | None:
            if not table:
                return None
            return min(table, key=lambda k: (-len(table[k]), -max(table[k]).toordinal(), k.int))

        usual_service = pick(svc_days)
        usual_provider = pick(prov_days)
        category = None
        if usual_service is not None and services[usual_service].category is not None:
            category = services[usual_service].category.strip().lower() or None
        staff_active = None
        if usual_provider is not None and providers[usual_provider].staff_id is not None:
            staff_active = staff[providers[usual_provider].staff_id].active

        # money
        spend_raw = sum(t.amount_cents for t in mine["txns"])
        ticket_txns = [t for t in mine["txns"] if t.kind in TICKET_KINDS]
        ticket_raw = sum(t.amount_cents for t in ticket_txns)
        ticket_total = max(0, ticket_raw)

        def txn_day(t) -> date:
            if t.appointment_id is not None:
                return day_of(appt_by_id[t.appointment_id].starts_at)
            return day_of(t.occurred_at)

        def ticket_on(day: date | None, ticket_txns=ticket_txns) -> int | None:
            if day is None:
                return None
            hits = [t.amount_cents for t in ticket_txns if txn_day(t) == day]
            return max(0, sum(hits)) if hits else None

        first_day = ordered_days[0] if ordered_days else None
        treatment_days = [d for d, appts in days.items() if any(not is_consult(a) for a in appts)]
        service_hits = [t.amount_cents for t in ticket_txns if usual_service and t.service_id == usual_service]

        # consults
        consult_visits = [a for a in visits if is_consult(a)]
        consult = max(consult_visits, key=lambda a: (day_of(a.starts_at), a.starts_at, a.id.int), default=None)
        converted = None
        quote, quote_invalid = None, False
        if consult is not None:
            c_day = day_of(consult.starts_at)
            converted = any(0 <= (d - c_day).days <= window and any(not is_consult(a) for a in days[d]) for d in days)
            quote, quote_invalid = _quote(consult.attributes.get("quoted_plan_cents"))

        # memberships
        latest = None
        if mine["memb"]:
            latest = min(
                mine["memb"],
                key=lambda m: (
                    0 if m.ends_at is None else 1,
                    -(m.ends_at.toordinal() if m.ends_at else 0),
                    -m.updated_at.timestamp(),
                    -m.id.int,
                ),
            )
        unknown_memb: dict[str, int] = {}
        for m in mine["memb"]:
            if m.status not in KNOWN_MEMBERSHIP_STATUSES:
                unknown_memb[m.status] = unknown_memb.get(m.status, 0) + 1

        # consent
        def latest_consent(kind: str, mine=mine) -> bool | None:
            rows_ = [c for c in mine["cons"] if c.kind == kind]
            return max(rows_, key=lambda c: (c.recorded_at, c.id.int)).granted if rows_ else None

        unknown_appt: dict[str, int] = {}
        for a in real:
            if a.status not in KNOWN_APPOINTMENT_STATUSES:
                unknown_appt[a.status] = unknown_appt.get(a.status, 0) + 1

        dob = p.date_of_birth
        invalid_dob = dob is not None and dob > today
        is_minor = False
        if dob is not None and not invalid_dob:
            age = today.year - dob.year - (1 if (today.month, today.day) < (dob.month, dob.day) else 0)
            is_minor = age < 18

        out[p.id] = {
            "patient_id": p.id,
            "date_of_birth": dob,
            "is_minor": is_minor,
            "invalid_dob": invalid_dob,
            "do_not_contact_raw": p.attributes.get("do_not_contact"),
            "deceased_raw": p.attributes.get("deceased"),
            "do_not_contact": _flag(p.attributes.get("do_not_contact")),
            "deceased": _flag(p.attributes.get("deceased")),
            "visit_count": len(ordered_days),
            "first_visit_day": first_day,
            "last_visit_day": ordered_days[-1] if ordered_days else None,
            "visit_days": tuple(kept),
            "visit_starts": tuple(min(a.starts_at for a in days[d]) for d in kept),
            "visit_days_without_service": sum(1 for d in ordered_days if all(a.service_id is None for a in days[d])),
            "consult_visit_days": sum(1 for d in ordered_days if all(is_consult(a) for a in days[d])),
            "has_future_booking": any(a.status == "booked" and a.starts_at >= now for a in real),
            "usual_service_id": usual_service,
            "usual_service_category_norm": category,
            "usual_service_visit_days": len(svc_days[usual_service]) if usual_service else 0,
            "usual_provider_id": usual_provider,
            "provider_staff_active": staff_active,
            "spend_cents": max(0, spend_raw),
            "ticket_total_cents": ticket_total,
            "average_ticket_cents": _half_up(ticket_total, len(ordered_days)) if ordered_days else None,
            "usual_service_ticket_total_cents": max(0, sum(service_hits)) if service_hits else None,
            "first_visit_ticket_cents": ticket_on(first_day),
            "first_treatment_ticket_cents": ticket_on(min(treatment_days) if treatment_days else None),
            "spend_percentile": None,
            "latest_consult_day": day_of(consult.starts_at) if consult else None,
            "latest_consult_service_id": consult.service_id if consult else None,
            "quoted_plan_cents": quote,
            "quoted_plan_invalid": quote_invalid,
            "converted_within_window": converted,
            "membership_rows": len(mine["memb"]),
            "has_active_membership": any(m.status == "active" for m in mine["memb"]),
            "latest_membership_status": latest.status if latest else None,
            "latest_membership_end": latest.ends_at if latest else None,
            "latest_membership_fee_cents": latest.recurring_amount_cents if latest else None,
            "prepaid_balance_cents": sum(
                m.prepaid_balance_cents for m in mine["memb"] if m.prepaid_balance_cents and m.prepaid_balance_cents > 0
            ),
            "consent_sms": latest_consent("sms"),
            "consent_email": latest_consent("email"),
            "has_phone": bool((p.phone or "").strip()),
            "has_email": bool((p.email or "").strip()),
            "sms_requires_explicit_opt_in": opt_in_required,
            "duplicate_appointments": duplicates,
            "completed_in_future": sum(1 for a in real if a.status == "completed" and a.starts_at > now),
            "stale_booked_in_past": sum(1 for a in real if a.status == "booked" and a.starts_at < now),
            "past_appointments": sum(1 for a in real if a.starts_at < now),
            "unknown_appointment_status": unknown_appt,
            "unknown_membership_status": unknown_memb,
            "negative_spend": spend_raw < 0,
            "negative_ticket": ticket_raw < 0,
            "outlier_transactions": sum(
                1
                for t in mine["txns"]
                if median is not None and t.amount_cents > 500_000 and t.amount_cents > 50 * median
            ),
        }

    # spend percentile over the scored cohort: at least one visit, not excluded (D10)
    def excluded(r: dict[str, Any]) -> bool:
        flags = {r["deceased"], r["do_not_contact"]}
        return r["is_minor"] or "true" in flags or "unparsable" in flags

    cohort = [r for r in out.values() if r["visit_count"] >= 1 and not excluded(r)]
    if len(cohort) >= max(cohort_min, 2):
        spends = [r["spend_cents"] for r in cohort]
        for r in cohort:
            r["spend_percentile"] = Fraction(sum(1 for s in spends if s < r["spend_cents"]), len(cohort) - 1)
    return out


def json_safe(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)
