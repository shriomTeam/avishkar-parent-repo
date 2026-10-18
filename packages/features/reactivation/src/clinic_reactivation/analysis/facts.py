"""The per-patient facts the rules run on: one SELECT over ``core``, no per-patient queries.

Everything in ``analysis/`` except this file is pure. This file reads one consistent snapshot
(a single statement, ``now`` bound as a parameter, never ``now()``) and returns frozen
``PatientFacts``. Its pure helpers (``reachable_from``) and ``exclusions`` carry no database access.

Rules implemented here come from docs/analysis-engine-spec.md 4.1 to 4.5 and 4.11, and from
docs/data-contract.md for what the real tables contain. Money is integer cents throughout.

PROVISIONAL: the quoted plan. ``core`` has nowhere to record one (data contract). Until the platform
adds one, a consult's quote is read from the consult appointment's ``attributes`` key
``quoted_plan_cents`` as a plain non-negative integer (JSON number, or a string of digits only).
Nothing in the importer sets it, so on imported data it is always None. Any other value is not
guessed: the quote is None and ``quoted_plan_invalid`` is set.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_reactivation.analysis.exclusions import (
    DEFAULT_COHORT_MIN,
    FlagValue,
    assign_spend_percentiles,
    dob_status,
    parse_flag_json,
)

VISIT_CAP = 200
OUTLIER_MIN_CENTS = 500_000  # $5,000
OUTLIER_MEDIAN_MULTIPLE = 50
CONSULT_WINDOW_DAYS = 60
STREAM_BATCH = 1000

APPOINTMENT_STATUSES = ("completed", "booked", "cancelled", "no_show")
MEMBERSHIP_STATUSES = ("active", "cancelled", "lapsed", "expired")
TICKET_KINDS = ("service", "product")

_DIGITS = re.compile(r"^[0-9]{1,12}$")


class BadTimezone(ValueError):
    """The tenant's timezone name is not a known IANA zone; the run fails before any work."""


# --- reachability ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReachabilityIngredients:
    """The raw inputs, so the rule lives in Python where a test can pin it to the engine."""

    consent_sms: bool | None  # latest consent row for sms, None when there is none
    consent_email: bool | None
    has_phone: bool
    has_email: bool
    sms_requires_explicit_opt_in: bool  # tenants.settings, default True


@dataclass(frozen=True, slots=True)
class Reachability:
    sms: bool
    email: bool

    @property
    def either(self) -> bool:
        return self.sms or self.email


def _channel_allowed(latest: bool | None, *, is_sms: bool, requires_opt_in: bool) -> bool:
    """clinic_engagement.compliance.can_contact for a patient, as a pure function."""
    if latest is False:
        return False
    return not (latest is None and is_sms and requires_opt_in)


def reachable_from(ingredients: ReachabilityIngredients) -> Reachability:
    """Mirrors ``can_contact`` per channel, plus the address check the sender makes separately
    (``run_due`` blocks a send with no address). Either channel makes the patient reachable."""
    sms = ingredients.has_phone and _channel_allowed(
        ingredients.consent_sms, is_sms=True, requires_opt_in=ingredients.sms_requires_explicit_opt_in
    )
    email = ingredients.has_email and _channel_allowed(
        ingredients.consent_email, is_sms=False, requires_opt_in=ingredients.sms_requires_explicit_opt_in
    )
    return Reachability(sms=sms, email=email)


# --- facts -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatientFacts:
    patient_id: uuid.UUID
    # identity and exclusion inputs
    date_of_birth: date | None
    is_minor: bool
    invalid_dob: bool
    do_not_contact_raw: Any
    deceased_raw: Any
    do_not_contact: FlagValue
    deceased: FlagValue
    # visits (D1: one visit = one distinct clinic-local day with a completed appointment)
    visit_count: int
    first_visit_day: date | None
    last_visit_day: date | None
    visit_days: tuple[date, ...]  # ascending, at most the 200 most recent
    visit_starts: tuple[datetime, ...]  # earliest start of each day in visit_days, UTC
    visit_days_without_service: int
    consult_visit_days: int
    has_future_booking: bool
    # usual service and provider
    usual_service_id: uuid.UUID | None
    usual_service_category_norm: str | None  # lower-cased, trimmed; None when blank or no service
    usual_service_visit_days: int
    usual_provider_id: uuid.UUID | None
    provider_staff_active: bool | None  # None: no provider, or the provider has no staff link
    # money, integer cents
    spend_cents: int
    ticket_total_cents: int
    average_ticket_cents: int | None
    usual_service_ticket_total_cents: int | None
    first_visit_ticket_cents: int | None
    first_treatment_ticket_cents: int | None
    spend_percentile: Fraction | None
    # consults
    latest_consult_day: date | None
    latest_consult_service_id: uuid.UUID | None
    quoted_plan_cents: int | None
    quoted_plan_invalid: bool
    converted_within_window: bool | None  # None when the patient has no consult
    # memberships
    membership_rows: int
    has_active_membership: bool
    latest_membership_status: str | None
    latest_membership_end: date | None
    latest_membership_fee_cents: int | None
    prepaid_balance_cents: int
    # reachability
    ingredients: ReachabilityIngredients
    # per-patient quality counters
    duplicate_appointments: int
    completed_in_future: int
    stale_booked_in_past: int
    past_appointments: int
    unknown_appointment_status: dict[str, int] = field(default_factory=dict)
    unknown_membership_status: dict[str, int] = field(default_factory=dict)
    negative_spend: bool = False
    negative_ticket: bool = False
    outlier_transactions: int = 0  # reported, never capped or dropped: spend keeps the full amount

    @property
    def reachability(self) -> Reachability:
        return reachable_from(self.ingredients)


# --- the query -------------------------------------------------------------------------------

_FACTS_SQL = text(
    """
WITH
prm AS MATERIALIZED (SELECT CAST(:now AS timestamptz) AS now, CAST(:tz AS text) AS tz),
tn AS MATERIALIZED (
  SELECT jsonb_exists(settings, 'sms_requires_explicit_opt_in') AS has_key,
         CAST(settings -> 'sms_requires_explicit_opt_in' AS text) AS val
  FROM core.tenants WHERE id = :tenant_id
),
appt AS MATERIALIZED (
  SELECT a.id, a.patient_id, a.service_id, a.provider_id, a.status, a.starts_at, a.attributes,
         CAST((a.starts_at AT TIME ZONE prm.tz) AS date) AS local_day,
         row_number() OVER (
           PARTITION BY a.patient_id, a.starts_at, a.service_id, a.status ORDER BY a.id
         ) AS rn
  FROM core.appointments a CROSS JOIN prm
  WHERE a.tenant_id = :tenant_id
),
ap AS MATERIALIZED (
  SELECT a.*, COALESCE(lower(btrim(s.category)) = 'consult', false) AS is_consult
  FROM appt a LEFT JOIN core.services s ON s.id = a.service_id
),
vis AS MATERIALIZED (
  SELECT ap.* FROM ap CROSS JOIN prm
  WHERE ap.rn = 1 AND ap.status = 'completed' AND ap.starts_at <= prm.now
),
vday AS MATERIALIZED (
  SELECT patient_id, local_day, min(starts_at) AS first_start,
         bool_or(is_consult) AS has_consult,
         bool_or(NOT is_consult) AS has_non_consult,
         bool_or(service_id IS NOT NULL) AS any_service
  FROM vis GROUP BY patient_id, local_day
),
vday_r AS MATERIALIZED (
  SELECT vday.*, row_number() OVER (PARTITION BY patient_id ORDER BY local_day DESC) AS r FROM vday
),
visit_agg AS MATERIALIZED (
  SELECT patient_id, count(*) AS visit_count, min(local_day) AS first_day, max(local_day) AS last_day,
         array_agg(local_day ORDER BY local_day) FILTER (WHERE r <= :cap) AS days,
         array_agg(first_start ORDER BY local_day) FILTER (WHERE r <= :cap) AS starts,
         count(*) FILTER (WHERE NOT any_service) AS days_without_service,
         count(*) FILTER (WHERE has_consult AND NOT has_non_consult) AS consult_days
  FROM vday_r GROUP BY patient_id
),
first_treat AS MATERIALIZED (
  SELECT patient_id, min(local_day) AS d FROM vday WHERE has_non_consult GROUP BY patient_id
),
astat AS MATERIALIZED (
  SELECT ap.patient_id,
         count(*) FILTER (WHERE ap.rn > 1) AS duplicates,
         count(*) FILTER (WHERE ap.rn = 1 AND ap.status = 'completed' AND ap.starts_at > prm.now)
           AS completed_future,
         count(*) FILTER (WHERE ap.rn = 1 AND ap.status = 'booked' AND ap.starts_at < prm.now) AS stale,
         count(*) FILTER (WHERE ap.rn = 1 AND ap.starts_at < prm.now) AS past_total,
         COALESCE(bool_or(ap.rn = 1 AND ap.status = 'booked' AND ap.starts_at >= prm.now), false)
           AS future_booking
  FROM ap CROSS JOIN prm GROUP BY ap.patient_id
),
unk AS MATERIALIZED (
  SELECT patient_id, CAST(jsonb_object_agg(status, c) AS text) AS j
  FROM (
    SELECT patient_id, status, count(*) AS c FROM ap
    WHERE rn = 1 AND status NOT IN ('completed', 'booked', 'cancelled', 'no_show')
    GROUP BY patient_id, status
  ) u GROUP BY patient_id
),
svc_rank AS MATERIALIZED (
  SELECT patient_id, service_id, count(*) AS days,
         row_number() OVER (
           PARTITION BY patient_id ORDER BY count(*) DESC, max(local_day) DESC, service_id
         ) AS r
  FROM (SELECT DISTINCT patient_id, local_day, service_id FROM vis WHERE service_id IS NOT NULL) d
  GROUP BY patient_id, service_id
),
usual_svc AS MATERIALIZED (
  SELECT r.patient_id, r.service_id, r.days, NULLIF(lower(btrim(s.category)), '') AS cat
  FROM svc_rank r JOIN core.services s ON s.id = r.service_id WHERE r.r = 1
),
prov_rank AS MATERIALIZED (
  SELECT patient_id, provider_id,
         row_number() OVER (
           PARTITION BY patient_id ORDER BY count(*) DESC, max(local_day) DESC, provider_id
         ) AS r
  FROM (SELECT DISTINCT patient_id, local_day, provider_id FROM vis WHERE provider_id IS NOT NULL) d
  GROUP BY patient_id, provider_id
),
usual_prov AS MATERIALIZED (
  SELECT r.patient_id, r.provider_id, st.active
  FROM prov_rank r JOIN core.providers p ON p.id = r.provider_id
  LEFT JOIN core.staff st ON st.id = p.staff_id WHERE r.r = 1
),
txn AS MATERIALIZED (
  SELECT t.patient_id, t.amount_cents, t.service_id,
         (t.kind IN ('service', 'product')) AS is_ticket,
         COALESCE(ad.local_day, CAST((t.occurred_at AT TIME ZONE prm.tz) AS date)) AS day
  FROM core.transactions t CROSS JOIN prm LEFT JOIN appt ad ON ad.id = t.appointment_id
  WHERE t.tenant_id = :tenant_id AND t.patient_id IS NOT NULL
),
med AS MATERIALIZED (
  SELECT CAST(percentile_cont(0.5) WITHIN GROUP (ORDER BY amount_cents) AS numeric) AS m
  FROM core.transactions WHERE tenant_id = :tenant_id AND amount_cents > 0
),
money AS MATERIALIZED (
  SELECT patient_id, sum(amount_cents) AS total,
         sum(amount_cents) FILTER (WHERE is_ticket) AS ticket,
         count(*) FILTER (
           WHERE amount_cents > 500000 AND amount_cents > 50 * (SELECT m FROM med)
         ) AS outliers
  FROM txn GROUP BY patient_id
),
day_ticket AS MATERIALIZED (
  SELECT t.patient_id,
         sum(t.amount_cents) FILTER (WHERE t.is_ticket AND t.day = va.first_day) AS first_visit,
         sum(t.amount_cents) FILTER (WHERE t.is_ticket AND t.day = ft.d) AS first_treatment
  FROM txn t JOIN visit_agg va ON va.patient_id = t.patient_id
  LEFT JOIN first_treat ft ON ft.patient_id = t.patient_id
  GROUP BY t.patient_id
),
svc_ticket AS MATERIALIZED (
  SELECT t.patient_id, sum(t.amount_cents) AS amt
  FROM txn t JOIN usual_svc u ON u.patient_id = t.patient_id AND u.service_id = t.service_id
  WHERE t.is_ticket GROUP BY t.patient_id
),
consult AS MATERIALIZED (
  SELECT DISTINCT ON (c.patient_id) c.patient_id, c.local_day, c.service_id,
         CAST(c.attributes -> 'quoted_plan_cents' AS text) AS quote
  FROM vis c WHERE c.is_consult
  ORDER BY c.patient_id, c.local_day DESC, c.starts_at DESC, c.id DESC
),
converted AS MATERIALIZED (
  SELECT c.patient_id,
         EXISTS (
           SELECT 1 FROM vday v
           WHERE v.patient_id = c.patient_id AND v.has_non_consult
             AND v.local_day BETWEEN c.local_day AND c.local_day + CAST(:window AS integer)
         ) AS yes
  FROM consult c
),
memb AS MATERIALIZED (
  SELECT patient_id, count(*) AS n,
         COALESCE(bool_or(status = 'active'), false) AS has_active,
         COALESCE(sum(prepaid_balance_cents) FILTER (WHERE prepaid_balance_cents > 0), 0) AS prepaid
  FROM core.memberships WHERE tenant_id = :tenant_id GROUP BY patient_id
),
memb_latest AS MATERIALIZED (
  SELECT DISTINCT ON (patient_id) patient_id, status, ends_at, recurring_amount_cents
  FROM core.memberships WHERE tenant_id = :tenant_id
  ORDER BY patient_id, ends_at DESC NULLS FIRST, updated_at DESC, id DESC
),
memb_unk AS MATERIALIZED (
  SELECT patient_id, CAST(jsonb_object_agg(status, c) AS text) AS j
  FROM (
    SELECT patient_id, status, count(*) AS c FROM core.memberships
    WHERE tenant_id = :tenant_id AND status NOT IN ('active', 'cancelled', 'lapsed', 'expired')
    GROUP BY patient_id, status
  ) u GROUP BY patient_id
),
latest_consent AS MATERIALIZED (
  SELECT DISTINCT ON (patient_id, kind) patient_id, kind, granted
  FROM core.consents WHERE tenant_id = :tenant_id AND kind IN ('sms', 'email')
  ORDER BY patient_id, kind, recorded_at DESC, id DESC
),
cons AS MATERIALIZED (
  SELECT patient_id,
         bool_or(granted) FILTER (WHERE kind = 'sms') AS sms,
         bool_or(granted) FILTER (WHERE kind = 'email') AS email
  FROM latest_consent GROUP BY patient_id
)
SELECT p.id AS patient_id, p.date_of_birth,
       CAST(p.attributes -> 'do_not_contact' AS text) AS dnc, CAST(p.attributes -> 'deceased' AS text) AS dec,
       (btrim(COALESCE(p.phone, '')) <> '') AS has_phone, (btrim(COALESCE(p.email, '')) <> '') AS has_email,
       tn.has_key AS opt_in_has_key, tn.val AS opt_in_val,
       cons.sms AS consent_sms, cons.email AS consent_email,
       COALESCE(va.visit_count, 0) AS visit_count, va.first_day, va.last_day, va.days, va.starts,
       COALESCE(va.days_without_service, 0) AS days_without_service,
       COALESCE(va.consult_days, 0) AS consult_days,
       COALESCE(astat.future_booking, false) AS future_booking,
       us.service_id AS usual_service_id, us.cat AS usual_category, COALESCE(us.days, 0) AS usual_service_days,
       up.provider_id AS usual_provider_id, up.active AS provider_active,
       COALESCE(money.total, 0) AS spend_total, money.ticket AS ticket_total,
       COALESCE(money.outliers, 0) AS outliers,
       svc_ticket.amt AS usual_service_ticket,
       day_ticket.first_visit AS first_visit_ticket, day_ticket.first_treatment AS first_treatment_ticket,
       consult.local_day AS consult_day, consult.service_id AS consult_service_id, consult.quote AS consult_quote,
       converted.yes AS converted,
       COALESCE(memb.n, 0) AS membership_rows, COALESCE(memb.has_active, false) AS has_active_membership,
       COALESCE(memb.prepaid, 0) AS prepaid_balance,
       memb_latest.status AS latest_membership_status, memb_latest.ends_at AS latest_membership_end,
       memb_latest.recurring_amount_cents AS latest_membership_fee,
       COALESCE(astat.duplicates, 0) AS duplicates, COALESCE(astat.completed_future, 0) AS completed_future,
       COALESCE(astat.stale, 0) AS stale, COALESCE(astat.past_total, 0) AS past_total,
       unk.j AS unknown_appt, memb_unk.j AS unknown_memb
FROM core.patients p
CROSS JOIN tn
LEFT JOIN visit_agg va ON va.patient_id = p.id
LEFT JOIN astat ON astat.patient_id = p.id
LEFT JOIN unk ON unk.patient_id = p.id
LEFT JOIN usual_svc us ON us.patient_id = p.id
LEFT JOIN usual_prov up ON up.patient_id = p.id
LEFT JOIN money ON money.patient_id = p.id
LEFT JOIN day_ticket ON day_ticket.patient_id = p.id
LEFT JOIN svc_ticket ON svc_ticket.patient_id = p.id
LEFT JOIN consult ON consult.patient_id = p.id
LEFT JOIN converted ON converted.patient_id = p.id
LEFT JOIN memb ON memb.patient_id = p.id
LEFT JOIN memb_latest ON memb_latest.patient_id = p.id
LEFT JOIN memb_unk ON memb_unk.patient_id = p.id
LEFT JOIN cons ON cons.patient_id = p.id
WHERE p.tenant_id = :tenant_id
ORDER BY p.id
"""
)


def _parse_quote(raw_json: str | None) -> tuple[int | None, bool]:
    """Strict: a JSON non-negative integer, or a string of 1 to 12 digits. (value, invalid)."""
    if raw_json is None:
        return None, False
    value = json.loads(raw_json)
    if value is None:
        return None, False
    if isinstance(value, bool):
        return None, True
    if isinstance(value, int):
        return (value, False) if value >= 0 else (None, True)
    if isinstance(value, str) and _DIGITS.match(value):
        return int(value), False
    return None, True


def _average_ticket(ticket_total: int, visits: int) -> int | None:
    if visits < 1:
        return None
    return (2 * ticket_total + visits) // (2 * visits)  # round half up, integers only


def _counts(raw_json: str | None) -> dict[str, int]:
    return {k: int(v) for k, v in json.loads(raw_json).items()} if raw_json else {}


def _opt_in_required(has_key: bool, raw: str | None) -> bool:
    """Same truthiness as ``tenant.settings.get('sms_requires_explicit_opt_in', True)``."""
    return True if not has_key else bool(json.loads(raw) if raw is not None else None)


def _to_facts(row: Any, today: date) -> PatientFacts:
    dnc_raw, dnc = parse_flag_json(row.dnc)
    dec_raw, dec = parse_flag_json(row.dec)
    is_minor, invalid_dob = dob_status(row.date_of_birth, today)
    spend_total = int(row.spend_total)
    ticket_raw = int(row.ticket_total) if row.ticket_total is not None else 0
    ticket_total = max(0, ticket_raw)
    quote, quote_invalid = _parse_quote(row.consult_quote)
    visits = int(row.visit_count)

    def clamped(v: int | None) -> int | None:
        return None if v is None else max(0, int(v))

    return PatientFacts(
        patient_id=row.patient_id,
        date_of_birth=row.date_of_birth,
        is_minor=is_minor,
        invalid_dob=invalid_dob,
        do_not_contact_raw=dnc_raw,
        deceased_raw=dec_raw,
        do_not_contact=dnc,
        deceased=dec,
        visit_count=visits,
        first_visit_day=row.first_day,
        last_visit_day=row.last_day,
        visit_days=tuple(row.days or ()),
        visit_starts=tuple(row.starts or ()),
        visit_days_without_service=int(row.days_without_service),
        consult_visit_days=int(row.consult_days),
        has_future_booking=bool(row.future_booking),
        usual_service_id=row.usual_service_id,
        usual_service_category_norm=row.usual_category,
        usual_service_visit_days=int(row.usual_service_days),
        usual_provider_id=row.usual_provider_id,
        provider_staff_active=row.provider_active,
        spend_cents=max(0, spend_total),
        ticket_total_cents=ticket_total,
        average_ticket_cents=_average_ticket(ticket_total, visits),
        usual_service_ticket_total_cents=clamped(row.usual_service_ticket),
        first_visit_ticket_cents=clamped(row.first_visit_ticket),
        first_treatment_ticket_cents=clamped(row.first_treatment_ticket),
        spend_percentile=None,
        latest_consult_day=row.consult_day,
        latest_consult_service_id=row.consult_service_id,
        quoted_plan_cents=quote,
        quoted_plan_invalid=quote_invalid,
        converted_within_window=None if row.consult_day is None else bool(row.converted),
        membership_rows=int(row.membership_rows),
        has_active_membership=bool(row.has_active_membership),
        latest_membership_status=row.latest_membership_status,
        latest_membership_end=row.latest_membership_end,
        latest_membership_fee_cents=None if row.latest_membership_fee is None else int(row.latest_membership_fee),
        prepaid_balance_cents=int(row.prepaid_balance),
        ingredients=ReachabilityIngredients(
            consent_sms=row.consent_sms,
            consent_email=row.consent_email,
            has_phone=bool(row.has_phone),
            has_email=bool(row.has_email),
            sms_requires_explicit_opt_in=_opt_in_required(row.opt_in_has_key, row.opt_in_val),
        ),
        duplicate_appointments=int(row.duplicates),
        completed_in_future=int(row.completed_future),
        stale_booked_in_past=int(row.stale),
        past_appointments=int(row.past_total),
        unknown_appointment_status=_counts(row.unknown_appt),
        unknown_membership_status=_counts(row.unknown_memb),
        negative_spend=spend_total < 0,
        negative_ticket=ticket_raw < 0,
        outlier_transactions=int(row.outliers),
    )


async def load_facts(
    session: AsyncSession,
    now: datetime,
    tz_name: str,
    *,
    visit_cap: int = VISIT_CAP,
    cohort_min: int = DEFAULT_COHORT_MIN,
    consult_window_days: int = CONSULT_WINDOW_DAYS,
) -> list[PatientFacts]:
    """Every patient of the session's tenant, ordered by patient id, as of ``now``.

    One statement, so one snapshot. Rows are streamed into frozen dataclasses; the only
    unbounded per-patient lists are capped to ``visit_cap`` in SQL.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise BadTimezone(tz_name) from None
    today = now.astimezone(tz).date()
    params = {
        "now": now.astimezone(UTC),
        "tz": tz_name,
        "tenant_id": current_tenant(session),
        "cap": visit_cap,
        "window": consult_window_days,
    }
    facts: list[PatientFacts] = []
    # Fresh imports have no planner statistics, so every CTE is estimated at one row and Postgres picks
    # nested loops that re-run each aggregate once per patient (quadratic). Equi-joins on patient_id
    # are always hashable, so forbid nested loops for this transaction (SET LOCAL ends with it; a RESET
    # here would fail in a transaction the query had aborted and hide the real error).
    # That setting inflates plan cost past the JIT threshold, and compiling this query costs seconds
    # for no gain, so JIT is switched off for the statement too.
    await session.execute(text("SET LOCAL enable_nestloop = off"))
    await session.execute(text("SET LOCAL jit = off"))
    result = await session.stream(_FACTS_SQL, params, execution_options={"yield_per": STREAM_BATCH})
    async for row in result:
        facts.append(_to_facts(row, today))
    return assign_spend_percentiles(facts, cohort_min=cohort_min)


__all__ = [
    "APPOINTMENT_STATUSES",
    "MEMBERSHIP_STATUSES",
    "BadTimezone",
    "PatientFacts",
    "Reachability",
    "ReachabilityIngredients",
    "load_facts",
    "reachable_from",
]
