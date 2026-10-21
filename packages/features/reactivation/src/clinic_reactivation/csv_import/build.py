"""Parsed lines -> ``PatientFacts``, in memory, by the same rules ``analysis/facts.py`` applies in SQL.

Pure: no database, no clock (``today`` is passed in). Each rule below names the SQL it mirrors; the
differential test proves the two paths give identical facts on the same data.

What a file cannot carry, and what the facts get instead:
  * visit times: ``visit_starts`` is empty (best-time is "needs visit times").
  * date of birth: no minors are excluded.
  * the quoted plan: ``None`` (the median first-treatment ticket is used).
  * appointment status counters: duplicates, completed-in-future and stale-booked are 0 and
    ``past_appointments`` is the visit count.
  * provider staff records: ``provider_staff_active`` is ``None``.

Identity: patients, services and providers get ids derived from their text (``derive_id``), so the same
file always gives the same ids and every tie the engine breaks by id is reproducible.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction

from clinic_reactivation.analysis.exclusions import DEFAULT_COHORT_MIN, FlagValue, assign_spend_percentiles
from clinic_reactivation.analysis.facts import (
    CONSULT_WINDOW_DAYS,
    OUTLIER_MEDIAN_MULTIPLE,
    OUTLIER_MIN_CENTS,
    VISIT_CAP,
    PatientFacts,
    ReachabilityIngredients,
    _average_ticket,
)
from clinic_reactivation.csv_import.parser import Line, ParsedFile, is_visit_line, service_key

NAMESPACE = uuid.UUID("6b1f0d7e-3c5a-4f0e-9a52-2a6d0b6f4c11")
TICKET_KINDS = ("service", "product")
CHURNED = ("cancelled", "lapsed", "expired")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


def derive_id(kind: str, key: str, namespace: uuid.UUID = NAMESPACE) -> uuid.UUID:
    """The same text always gives the same id. Patients use the trimmed id as written; services and
    providers use their whitespace-collapsed, case-folded name. Tests pass their own namespace because
    database ids are global and test rows stay behind."""
    return uuid.uuid5(namespace, f"{kind}:{key}")


@dataclass(frozen=True)
class Built:
    facts: list[PatientFacts]
    service_names: dict[uuid.UUID, str]
    external_ids: dict[uuid.UUID, str]
    display_names: dict[uuid.UUID, str | None]
    notes: dict[str, int] = field(default_factory=dict)  # note code -> patients affected
    visit_days: int = 0


def _median(values: list[int]) -> Fraction | None:
    """percentile_cont(0.5): the middle value, or the mean of the two middle ones."""
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return Fraction(ordered[mid])
    return Fraction(ordered[mid - 1] + ordered[mid], 2)


def _first(lines: list[Line], attr: str):
    for ln in lines:
        value = getattr(ln, attr)
        if value is not None:
            return value
    return None


def _flag(value: bool | None) -> tuple[object, FlagValue]:
    if value is None:
        return None, FlagValue.ABSENT
    return value, FlagValue.TRUE if value else FlagValue.FALSE


def build_facts(
    parsed: ParsedFile,
    *,
    today: date,
    requires_opt_in: bool = True,
    cohort_min: int = DEFAULT_COHORT_MIN,
    window_days: int = CONSULT_WINDOW_DAYS,
    namespace: uuid.UUID = NAMESPACE,
) -> Built:
    by_patient: dict[str, list[Line]] = defaultdict(list)
    for ln in parsed.lines:
        by_patient[ln.patient_id].append(ln)

    # facts._FACTS_SQL `med`: the median of every positive transaction amount in the tenant.
    median = _median([ln.amount for ln in parsed.lines if ln.amount > 0])
    outlier_floor = None if median is None else max(Fraction(OUTLIER_MIN_CENTS), OUTLIER_MEDIAN_MULTIPLE * median)

    service_names: dict[uuid.UUID, str] = {}
    for ln in parsed.lines:
        if ln.service_name is not None:
            service_names.setdefault(
                derive_id("service", service_key(ln.service_name), namespace), " ".join(ln.service_name.split())
            )

    notes: dict[str, int] = defaultdict(int)
    facts: list[PatientFacts] = []
    external_ids: dict[uuid.UUID, str] = {}
    display_names: dict[uuid.UUID, str | None] = {}
    total_days = 0
    for external_id in sorted(by_patient):
        lines = by_patient[external_id]
        f, n_days = _one(external_id, lines, today, requires_opt_in, outlier_floor, window_days, notes, namespace)
        total_days += n_days
        facts.append(f)
        external_ids[f.patient_id] = external_id
        name = _first(lines, "patient_name")
        display_names[f.patient_id] = " ".join(name.split()) if name else None
    return Built(
        assign_spend_percentiles(facts, cohort_min=cohort_min),
        service_names, external_ids, display_names, dict(notes), total_days,
    )  # fmt: skip


def _one(
    external_id: str,
    lines: list[Line],
    today: date,
    requires_opt_in: bool,
    outlier_floor: Fraction | None,
    window_days: int,
    notes: dict[str, int],
    namespace: uuid.UUID,
) -> tuple[PatientFacts, int]:
    pid = derive_id("patient", external_id, namespace)

    # --- money (facts txn/money/day_ticket/svc_ticket) -----------------------------------------------
    spend_total = sum(ln.amount for ln in lines)
    ticket = [ln for ln in lines if ln.line_kind in TICKET_KINDS]
    ticket_raw = sum(ln.amount for ln in ticket)
    ticket_total = max(0, ticket_raw)
    outliers = 0 if outlier_floor is None else sum(1 for ln in lines if ln.amount > outlier_floor)

    # --- visits (vday): a visit day has a service or product line of 0 or more ------------------------
    visit_lines = [ln for ln in lines if is_visit_line(ln)]
    group_type: dict[tuple[date, str | None], str] = {}
    for ln in lines:
        if ln.visit_type is not None:
            group_type[(ln.visit_date, ln.visit_id)] = ln.visit_type
    groups: dict[tuple[date, str | None], list[Line]] = defaultdict(list)
    for ln in visit_lines:
        groups[(ln.visit_date, ln.visit_id)].append(ln)

    # One "unit" per service line (an appointment), or one per visit that has no service line.
    day_units: dict[date, list[tuple[bool, str | None]]] = defaultdict(list)  # (is_consult, service key)
    for (day, _vid), members in groups.items():
        consult_visit = group_type.get((day, _vid)) == "consult"
        services = [ln for ln in members if ln.line_kind == "service"]
        if not services:
            day_units[day].append((consult_visit, None))
        for ln in services:
            category = ln.service_category
            is_consult = consult_visit or (category is not None and service_key(category) == "consult")
            day_units[day].append((is_consult, service_key(ln.service_name)))

    days = sorted(day_units)
    visits = len(days)
    has_consult = {d for d in days if any(c for c, _ in day_units[d])}
    has_non_consult = {d for d in days if any(not c for c, _ in day_units[d])}
    any_service = {d for d in days if any(s is not None for _, s in day_units[d])}
    first_day = days[0] if days else None
    last_day = days[-1] if days else None
    first_treat = min(has_non_consult) if has_non_consult else None

    # --- usual service (svc_rank: distinct days, latest day, service id) ------------------------------
    service_days: dict[str, set[date]] = defaultdict(set)
    for d in days:
        for _, s in day_units[d]:
            if s is not None:
                service_days[s].add(d)
    usual_key = min(
        service_days,
        key=lambda s: (
            -len(service_days[s]),
            -max(service_days[s]).toordinal(),
            derive_id("service", s, namespace).int,
        ),
        default=None,
    )
    usual_category = None
    if usual_key is not None:
        for ln in lines:
            if ln.service_name is not None and ln.service_category and service_key(ln.service_name) == usual_key:
                usual_category = service_key(ln.service_category)
                break
    usual_ticket = None
    if usual_key is not None:
        matching = [ln.amount for ln in ticket if ln.service_name and service_key(ln.service_name) == usual_key]
        usual_ticket = max(0, sum(matching)) if matching else None

    # --- usual provider (prov_rank) ----------------------------------------------------------------------
    provider_days: dict[str, set[date]] = defaultdict(set)
    for ln in visit_lines:
        if ln.provider_name:
            provider_days[service_key(ln.provider_name)].add(ln.visit_date)
    usual_provider = min(
        provider_days,
        key=lambda p: (
            -len(provider_days[p]),
            -max(provider_days[p]).toordinal(),
            derive_id("provider", p, namespace).int,
        ),
        default=None,
    )

    # --- first-visit and first-treatment tickets (day_ticket) --------------------------------------------
    def day_ticket(day: date | None) -> int | None:
        if day is None:
            return None
        amounts = [ln.amount for ln in ticket if ln.visit_date == day]
        return max(0, sum(amounts)) if amounts else None

    # --- consults (consult, converted) ---------------------------------------------------------------------
    consult_day = max(has_consult) if has_consult else None
    consult_service = None
    converted = None
    if consult_day is not None:
        keys = [s for c, s in day_units[consult_day] if c and s is not None]
        consult_service = min((derive_id("service", s, namespace) for s in keys), key=lambda u: u.int, default=None)
        end = consult_day + timedelta(days=window_days)
        converted = any(consult_day <= d <= end for d in has_non_consult)

    # --- memberships (memb, memb_latest) ------------------------------------------------------------------
    status = _first(lines, "membership_status")
    ended_on = _first(lines, "membership_ended_on")
    fee = _first(lines, "membership_monthly_fee")
    prepaid = _first(lines, "prepaid_balance") or 0
    real_status = status if status not in (None, "none") else None
    rows = 1 if (real_status is not None or prepaid > 0) else 0
    if real_status is None and (ended_on is not None or fee is not None):
        notes["membership_details_ignored"] += 1

    # --- reachability and exclusions ---------------------------------------------------------------------
    email, phone = _first(lines, "email"), _first(lines, "phone")
    has_email = bool(email) and bool(_EMAIL.match(email))
    has_phone = bool(phone) and len(re.sub(r"\D", "", phone)) >= 7
    if email and not has_email:
        notes["email_treated_as_missing"] += 1
    if phone and not has_phone:
        notes["phone_treated_as_missing"] += 1
    next_appointment = _first(lines, "next_appointment_date")
    if next_appointment is not None and next_appointment < today:
        notes["past_next_appointment_ignored"] += 1
    dnc_raw, dnc = _flag(_first(lines, "do_not_contact"))
    dec_raw, dec = _flag(_first(lines, "deceased"))

    fact = PatientFacts(
        patient_id=pid,
        date_of_birth=None,
        is_minor=False,
        invalid_dob=False,
        do_not_contact_raw=dnc_raw,
        deceased_raw=dec_raw,
        do_not_contact=dnc,
        deceased=dec,
        visit_count=visits,
        first_visit_day=first_day,
        last_visit_day=last_day,
        visit_days=tuple(days[-VISIT_CAP:]),
        visit_starts=(),
        visit_days_without_service=sum(1 for d in days if d not in any_service),
        consult_visit_days=sum(1 for d in has_consult if d not in has_non_consult),
        has_future_booking=next_appointment is not None and next_appointment >= today,
        usual_service_id=None if usual_key is None else derive_id("service", usual_key, namespace),
        usual_service_category_norm=usual_category,
        usual_service_visit_days=0 if usual_key is None else len(service_days[usual_key]),
        usual_provider_id=None if usual_provider is None else derive_id("provider", usual_provider, namespace),
        provider_staff_active=None,
        spend_cents=max(0, spend_total),
        ticket_total_cents=ticket_total,
        average_ticket_cents=_average_ticket(ticket_total, visits),
        usual_service_ticket_total_cents=usual_ticket,
        first_visit_ticket_cents=day_ticket(first_day),
        first_treatment_ticket_cents=day_ticket(first_treat),
        spend_percentile=None,
        latest_consult_day=consult_day,
        latest_consult_service_id=consult_service,
        quoted_plan_cents=None,
        quoted_plan_invalid=False,
        converted_within_window=converted,
        membership_rows=rows,
        has_active_membership=real_status == "active",
        latest_membership_status=real_status,
        latest_membership_end=ended_on if real_status is not None else None,
        latest_membership_fee_cents=fee if real_status is not None else None,
        prepaid_balance_cents=prepaid,
        ingredients=ReachabilityIngredients(
            consent_sms=_first(lines, "sms_consent"),
            consent_email=_first(lines, "email_consent"),
            has_phone=has_phone,
            has_email=has_email,
            sms_requires_explicit_opt_in=requires_opt_in,
        ),
        duplicate_appointments=0,
        completed_in_future=0,
        stale_booked_in_past=0,
        past_appointments=visits,
        unknown_appointment_status={},
        unknown_membership_status={},
        negative_spend=spend_total < 0,
        negative_ticket=ticket_raw < 0,
        outlier_transactions=outliers,
    )
    return fact, visits
