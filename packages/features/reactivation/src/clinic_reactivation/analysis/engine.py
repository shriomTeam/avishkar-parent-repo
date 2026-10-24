"""analyse(): the whole analysis for one run (spec sections 1, 4.11, 5 and 6).

Pure: it takes facts and settings and returns an immutable ``RunResult``; it saves nothing, so a failed run
leaves nothing behind. In order: exclusions (counted by reason), then per patient classification, score and
points inside their own ``try/except`` so one corrupt patient cannot break the run, then the per-type and
run aggregates, the summary and the quality report, and finally the invariants of spec section 6.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clinic_reactivation.analysis.exclusions import FlagValue, assign_spend_percentiles, exclusion_reason
from clinic_reactivation.analysis.facts import PatientFacts, ReachabilityIngredients
from clinic_reactivation.analysis.points import (
    PreviousRun,
    analysis_points,
    change_counts,
    data_available,
)
from clinic_reactivation.analysis.revenue import (
    FLAG_NO_SPEND,
    NEW,
    RETENTION,
    TYPE_KINDS,
    Basis,
    MeasuredRate,
    RevenueContext,
    RevenueInput,
    practice_median_first_treatment_ticket,
    revenue_basis,
    summarise_revenue,
)
from clinic_reactivation.analysis.scoring import PastResponse, RatioInputs, likelihood_score, ordering_key
from clinic_reactivation.analysis.settings import ReactivationSettings, ratio_fraction
from clinic_reactivation.analysis.types import (
    STATUS_ACTIVE,
    STATUS_AT_RISK,
    STATUS_DORMANT,
    Classification,
    classify,
)

ERR_BAD_TIMEZONE = "bad_timezone"
ERR_TOO_MANY_ERRORS = "too_many_patient_errors"
ERR_INVARIANT = "invariant_failed"

SAMPLE_CAP = 20
NO_COMPLETED_VISITS = "no_completed_visits"
EXCLUSION_KEYS = {
    "deceased": "excluded_deceased",
    "do_not_contact": "excluded_do_not_contact",
    "unparsable_exclusion_flag": "unparsable_exclusion_flag",
    "minor": "excluded_minor",
    NO_COMPLETED_VISITS: NO_COMPLETED_VISITS,
}
SCORED_STATUSES = {STATUS_DORMANT, STATUS_AT_RISK, STATUS_ACTIVE}
MAX_OVERDUE_RATIO = Decimal("9999.99")  # run_patients.overdue_ratio is Numeric(6, 2)
TWO_PLACES = Decimal("0.01")


class RunFailed(Exception):
    """The run cannot produce a trustworthy result. `error_code` goes to runs.error_code; `detail` carries
    no patient data."""

    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(f"{error_code}: {detail}" if detail else error_code)
        self.error_code = error_code
        self.detail = detail


class CorruptFacts(ValueError):
    """A patient's facts are not the shape the engine relies on."""


# --- output ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunPatientOut:
    patient_id: uuid.UUID
    status: str
    primary_type: str | None
    matched_types: tuple[str, ...]
    last_visit_at: datetime | None
    days_since_last_visit: int
    overdue_ratio: Decimal
    visit_count: int
    total_spend_cents: int
    usual_service_id: uuid.UUID | None
    usual_provider_id: uuid.UUID | None
    revenue_basis_cents: int
    revenue_kind: str
    likelihood_score: int
    points: dict[str, Any]
    change: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunTypeOut:
    type_key: str
    patient_count: int
    basis_total_cents: int
    rate_low: Decimal
    rate_high: Decimal
    rate_source: str
    revenue_low_cents: int
    revenue_high_cents: int
    revenue_kind: str
    top_service_id: uuid.UUID | None


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        raise TypeError("a float reached the run result; money and rates are never floats")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, set | frozenset):
        return sorted(_jsonable(v) for v in value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _jsonable(getattr(value, f.name)) for f in fields(value)}
    raise TypeError(f"cannot serialise {type(value).__name__}")


@dataclass(frozen=True, slots=True)
class RunResult:
    patients: tuple[RunPatientOut, ...]
    types: tuple[RunTypeOut, ...]
    summary: dict[str, Any]
    quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(self)

    def canonical_json(self) -> str:
        """Sorted keys, no spaces, no floats: equal results give byte-identical strings."""
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode()).hexdigest()


# --- checking one patient's facts ------------------------------------------------------------

_INT_FIELDS = (
    "visit_count", "visit_days_without_service", "consult_visit_days", "usual_service_visit_days", "spend_cents",
    "ticket_total_cents", "membership_rows", "prepaid_balance_cents", "duplicate_appointments",
    "completed_in_future", "stale_booked_in_past", "past_appointments", "outlier_transactions",
)  # fmt: skip
_OPTIONAL_INT_FIELDS = (
    "average_ticket_cents", "usual_service_ticket_total_cents", "first_visit_ticket_cents",
    "first_treatment_ticket_cents", "quoted_plan_cents", "latest_membership_fee_cents",
)  # fmt: skip
_OPTIONAL_DATE_FIELDS = (
    "first_visit_day", "last_visit_day", "latest_consult_day", "latest_membership_end", "date_of_birth",
)  # fmt: skip
_BOOL_FIELDS = (
    "is_minor", "invalid_dob", "has_future_booking", "has_active_membership", "negative_spend", "negative_ticket",
    "quoted_plan_invalid",
)  # fmt: skip


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_date(value: Any) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _check_facts(f: PatientFacts) -> None:
    if not isinstance(f, PatientFacts):
        raise CorruptFacts("not a PatientFacts")
    for name in _INT_FIELDS:
        value = getattr(f, name)
        if not _is_int(value) or value < 0:
            raise CorruptFacts(name)
    if f.prepaid_balance_cents < 0:
        raise CorruptFacts("prepaid_balance_cents")
    for name in _OPTIONAL_INT_FIELDS:
        value = getattr(f, name)
        if value is not None and not _is_int(value):
            raise CorruptFacts(name)
    for name in _OPTIONAL_DATE_FIELDS:
        value = getattr(f, name)
        if value is not None and not _is_date(value):
            raise CorruptFacts(name)
    for name in _BOOL_FIELDS:
        if type(getattr(f, name)) is not bool:
            raise CorruptFacts(name)
    if f.visit_count >= 1 and f.last_visit_day is None:
        raise CorruptFacts("last_visit_day")
    if not isinstance(f.do_not_contact, FlagValue) or not isinstance(f.deceased, FlagValue):
        raise CorruptFacts("exclusion flags")
    if not isinstance(f.ingredients, ReachabilityIngredients):
        raise CorruptFacts("ingredients")
    if f.spend_percentile is not None and not isinstance(f.spend_percentile, Fraction):
        raise CorruptFacts("spend_percentile")
    if not isinstance(f.visit_days, tuple) or not all(_is_date(d) for d in f.visit_days):
        raise CorruptFacts("visit_days")
    if not isinstance(f.visit_starts, tuple) or not all(
        isinstance(d, datetime) and d.tzinfo is not None for d in f.visit_starts
    ):
        raise CorruptFacts("visit_starts")
    for counts in (f.unknown_appointment_status, f.unknown_membership_status):
        if not isinstance(counts, dict) or not all(isinstance(k, str) and _is_int(v) for k, v in counts.items()):
            raise CorruptFacts("status counts")


# --- the per-patient step --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Scored:
    facts: PatientFacts
    classification: Classification
    score: int | None  # dormant and at-risk patients only
    points: dict[str, Any] | None
    basis: Basis


def _lead(f: PatientFacts, c: Classification, names: Mapping[uuid.UUID, str]) -> str:
    if f.usual_service_id is None:
        return f"Last visit {c.days_since_last_visit} days ago, standard rebooking interval {c.interval_days} days"
    name = names.get(f.usual_service_id)
    usual = f"usual {name}" if name else "usual service"
    return f"Last visit {c.days_since_last_visit} days ago, {usual} every {c.interval_days} days"


def _score_one(
    f: PatientFacts,
    settings: ReactivationSettings,
    context: RevenueContext,
    past_responders: Mapping[uuid.UUID, PastResponse | str],
    previous: PreviousRun | None,
    now: datetime,
    tz_name: str,
) -> _Scored:
    c = classify(f, settings, now, tz_name)
    if c.status not in (STATUS_DORMANT, STATUS_AT_RISK):
        return _Scored(f, c, None, None, Basis(0, NEW))
    response = PastResponse(past_responders.get(f.patient_id, PastResponse.NEVER))
    score = likelihood_score(f, RatioInputs(c.days_since_last_visit, c.interval_days), response)
    points = analysis_points(f, c.status, c.primary_type, settings, now, tz_name, previous)
    basis = (
        revenue_basis(c.primary_type, f, context, settings)
        if c.status == STATUS_DORMANT and c.primary_type is not None
        else Basis(0, NEW)
    )
    return _Scored(f, c, score, points, basis)


def _plain(value: Any) -> str | None:
    return None if value is None else str(value)


def _row(s: _Scored, names: Mapping[uuid.UUID, str]) -> RunPatientOut:
    f, c = s.facts, s.classification
    ratio = min(
        (Decimal(c.days_since_last_visit) / Decimal(c.interval_days)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
        MAX_OVERDUE_RATIO,
    )
    lead = _lead(f, c, names)
    if c.status == STATUS_AT_RISK:
        reasons = (f"{lead}, due again soon",)
    elif c.type_reasons:
        reasons = (lead, *c.type_reasons)
    else:
        reasons = (lead, "Dormant, but matches none of the enabled patient types")
    return RunPatientOut(
        patient_id=f.patient_id,
        status=c.status,
        primary_type=c.primary_type,
        matched_types=c.matched_types,
        last_visit_at=f.visit_starts[-1] if f.visit_starts else None,
        days_since_last_visit=c.days_since_last_visit,
        overdue_ratio=ratio,
        visit_count=f.visit_count,
        total_spend_cents=f.spend_cents,
        usual_service_id=f.usual_service_id,
        usual_provider_id=f.usual_provider_id,
        revenue_basis_cents=s.basis.cents,
        revenue_kind=s.basis.kind,
        likelihood_score=s.score,
        points=s.points or {},
        change=_plain((s.points or {}).get("change_since_last", {}).get("change")),
        reasons=reasons,
    )


# --- quality ---------------------------------------------------------------------------------


def _entry(total: int, ids: Iterable[uuid.UUID]) -> dict[str, Any]:
    unique = sorted(set(ids), key=lambda u: u.int)
    return {"count": total, "patients": len(unique), "sample_ids": [str(i) for i in unique[:SAMPLE_CAP]]}


def _sum_entry(items: Iterable[tuple[uuid.UUID, int]]) -> dict[str, Any]:
    pairs = [(pid, n) for pid, n in items if n]
    return _entry(sum(n for _, n in pairs), (pid for pid, _ in pairs))


def _per_value(items: Iterable[tuple[uuid.UUID, Mapping[str, int]]]) -> dict[str, Any]:
    by_value: dict[str, list[tuple[uuid.UUID, int]]] = {}
    for pid, counts in items:
        for value, n in counts.items():
            by_value.setdefault(value, []).append((pid, n))
    return {value: _sum_entry(pairs) for value, pairs in sorted(by_value.items())}


@dataclass(slots=True)
class _Internal:
    """What the invariants check against; never part of the result."""

    total: int
    scored: list[_Scored]
    excluded: dict[uuid.UUID, str]
    errors: dict[uuid.UUID, str]


def _enforce_tolerance(errors: Mapping[Any, str], total: int, settings: ReactivationSettings) -> None:
    tolerance = ratio_fraction(settings.limits.patient_error_tolerance)
    if len(errors) * tolerance.denominator > tolerance.numerator * total:
        raise RunFailed(
            ERR_TOO_MANY_ERRORS, f"{len(errors)} of {total} patients could not be processed (limit {tolerance:.0%})"
        )


def _build(
    facts: list[PatientFacts],
    settings: ReactivationSettings,
    measured_rates: Mapping[str, MeasuredRate],
    past_responders: Mapping[uuid.UUID, PastResponse | str],
    previous_dormant_ids: Iterable[uuid.UUID] | None,
    now: datetime,
    tz_name: str,
    service_names: Mapping[uuid.UUID, str],
) -> tuple[RunResult, _Internal]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise RunFailed(ERR_BAD_TIMEZONE, "the practice's time zone is not recognised") from None
    ids = [getattr(f, "patient_id", None) for f in facts]
    if not all(isinstance(i, uuid.UUID) for i in ids) or len(set(ids)) != len(ids):
        raise RunFailed(ERR_INVARIANT, "patient ids are missing or not unique")

    ordered = sorted(facts, key=lambda f: f.patient_id.int)
    total = len(ordered)
    previous = None if previous_dormant_ids is None else PreviousRun(frozenset(previous_dormant_ids))

    # 1. exclusions first, each patient on its own
    errors: dict[uuid.UUID, str] = {}
    excluded: dict[uuid.UUID, str] = {}
    eligible: list[PatientFacts] = []
    for f in ordered:
        try:
            _check_facts(f)
            reason = exclusion_reason(f) or (NO_COMPLETED_VISITS if f.visit_count < 1 else None)
            if reason is None:
                eligible.append(f)
            else:
                excluded[f.patient_id] = reason
        except Exception as e:  # noqa: BLE001 - one corrupt patient must never break the run
            errors[f.patient_id] = type(e).__name__
    _enforce_tolerance(errors, total, settings)

    # 2. classify, score and attach points. A failure here changes who is in the spend cohort, so the
    #    percentiles are recomputed and the pass repeated without that patient.
    while True:
        pool = [f for f in eligible if f.patient_id not in errors]
        pool = assign_spend_percentiles(pool, cohort_min=settings.limits.spend_cohort_minimum)
        context = RevenueContext(practice_median_first_treatment_ticket(pool))
        scored: list[_Scored] = []
        failed: dict[uuid.UUID, str] = {}
        for f in pool:
            try:
                scored.append(_score_one(f, settings, context, past_responders, previous, now, tz_name))
            except Exception as e:  # noqa: BLE001
                failed[f.patient_id] = type(e).__name__
        if not failed:
            break
        errors.update(failed)
        _enforce_tolerance(errors, total, settings)

    # 3. aggregates
    revenue = summarise_revenue(
        [RevenueInput(s.facts, s.classification.status, s.classification.primary_type, s.classification.matched_types)
         for s in scored],
        context, settings, measured_rates,
    )  # fmt: skip
    statuses = {s.classification.patient_id: s.classification.status for s in scored}
    changes = change_counts(previous, statuses)
    rows = sorted(
        (_row(s, service_names) for s in scored if s.classification.status in (STATUS_DORMANT, STATUS_AT_RISK)),
        key=lambda r: ordering_key(r.likelihood_score, r.total_spend_cents, r.patient_id),
    )
    dormant = [s for s in scored if s.classification.status == STATUS_DORMANT]
    at_risk = [s for s in scored if s.classification.status == STATUS_AT_RISK]
    unclassified = [s for s in dormant if s.classification.primary_type is None]

    top_service: dict[str, uuid.UUID | None] = {}
    for row in revenue.rows:
        counts = Counter(
            s.facts.usual_service_id
            for s in dormant
            if s.classification.primary_type == row.type_key and s.facts.usual_service_id is not None
        )
        top_service[row.type_key] = min(counts, key=lambda sid: (-counts[sid], sid.int)) if counts else None
    types = tuple(
        RunTypeOut(
            type_key=r.type_key, patient_count=r.patient_count, basis_total_cents=r.basis_total_cents,
            rate_low=r.rate_low, rate_high=r.rate_high, rate_source=r.rate_source,
            revenue_low_cents=r.revenue_low_cents, revenue_high_cents=r.revenue_high_cents,
            revenue_kind=r.revenue_kind, top_service_id=top_service[r.type_key],
        )
        for r in revenue.rows
    )  # fmt: skip

    # 4. data availability, warnings, quality and summary
    usable = [f for f in ordered if f.patient_id not in errors]
    available = data_available(usable)
    cohort_size = len(pool)
    cohort_ok = cohort_size >= settings.limits.spend_cohort_minimum
    enabled_types = [row.type_key for row in revenue.rows]
    types_available = {
        key: {
            "lapsed_high_value": cohort_ok or settings.types.lapsed_high_value.spend_cents_min is not None,
            "churned_member": available["memberships"],
            "unused_balance": available["memberships"],
            "consult_not_converted": any(f.latest_consult_day is not None for f in pool),
        }.get(key, True)
        for key in enabled_types
    }

    no_visit_patients = sum(1 for f in usable if f.visit_count == 0)
    past_total = sum(f.past_appointments for f in usable)
    stale_total = sum(f.stale_booked_in_past for f in usable)
    warnings = set()
    if total == 0:
        warnings.add("no_patients")
    if not enabled_types:
        warnings.add("no_types_enabled")
    if "lapsed_high_value" in enabled_types and not cohort_ok and pool:
        warnings.add("cohort_too_small_for_percentile")
    if total and no_visit_patients * 2 > total:
        warnings.add("data_looks_incomplete")
    if past_total and stale_total * 10 > 3 * past_total:
        warnings.add("appointment_status_not_maintained")

    by_reason: dict[str, list[uuid.UUID]] = {}
    for pid, reason in excluded.items():
        by_reason.setdefault(reason, []).append(pid)
    quality: dict[str, Any] = {
        "patients_total": _entry(total, ()),
        "patients_scored": _entry(len(scored), ()),
        "patient_errors": {
            "count": len(errors),
            "items": [
                {"patient_id": str(pid), "error_class": errors[pid]}
                for pid in sorted(errors, key=lambda u: u.int)[:SAMPLE_CAP]
            ],
        },  # fmt: skip
        "duplicate_appointments": _sum_entry((f.patient_id, f.duplicate_appointments) for f in usable),
        "completed_in_future": _sum_entry((f.patient_id, f.completed_in_future) for f in usable),
        "stale_booked_in_past": _sum_entry((f.patient_id, f.stale_booked_in_past) for f in usable),
        "outlier_amounts": _sum_entry((f.patient_id, f.outlier_transactions) for f in usable),
        "unknown_appointment_status": _per_value((f.patient_id, f.unknown_appointment_status) for f in usable),
        "unknown_membership_status": _per_value((f.patient_id, f.unknown_membership_status) for f in usable),
        "negative_spend_patients": _sum_entry((f.patient_id, int(f.negative_spend)) for f in usable),
        "negative_ticket_patients": _sum_entry((f.patient_id, int(f.negative_ticket)) for f in usable),
        "invalid_dob": _sum_entry((f.patient_id, int(f.invalid_dob)) for f in usable),
        "missing_service_on_visits": _sum_entry(
            (s.facts.patient_id, int("missing_service_on_visits" in s.classification.quality_flags)) for s in scored
        ),
        "invalid_rebooking_interval": _sum_entry(
            (s.facts.patient_id, int("invalid_rebooking_interval" in s.classification.quality_flags)) for s in scored
        ),
        "zero_basis_patients": _sum_entry((s.facts.patient_id, int(FLAG_NO_SPEND in s.basis.flags)) for s in dormant),
        "unclassified_dormant": _entry(len(unclassified), (s.facts.patient_id for s in unclassified)),
        # impossible by the schema (data contract), kept at zero so the report keeps one shape
        "excluded_inactive": _entry(0, ()),
        "null_amount_transactions": _entry(0, ()),
        "naive_timestamps": _entry(0, ()),
        "data_available": available,
        "exclusion_flags_not_importable": True,
        "currency_assumed": "USD",
        "spend_cohort_size": cohort_size,
        "warnings": sorted(warnings),
    }
    for reason, key in EXCLUSION_KEYS.items():
        quality[key] = _entry(len(by_reason.get(reason, ())), by_reason.get(reason, ()))

    summary: dict[str, Any] = {
        "as_of": now.astimezone(UTC).isoformat(),
        "patients_total": total,
        "patients_scored": len(scored),
        "patients_excluded": len(excluded),
        "patients_errored": len(errors),
        "dormant_count": len(dormant),
        "at_risk_count": len(at_risk),
        "active_count": len(scored) - len(dormant) - len(at_risk),
        "unclassified_dormant": len(unclassified),
        "new_revenue_low_cents": revenue.new_low_cents,
        "new_revenue_high_cents": revenue.new_high_cents,
        "retention_value_cents": revenue.retention_cents,
        "first_run": changes.first_run,
        "newly_dormant": changes.new,
        "unchanged_dormant": changes.unchanged,
        "returned_since_last": changes.returned_since_last,
        "data_available": available,
        "types_data_available": types_available,
    }
    if settings.points.revenue_at_risk:
        summary["at_risk_revenue_cents"] = revenue.at_risk_revenue_cents

    result = RunResult(patients=tuple(rows), types=types, summary=summary, quality=quality)
    return result, _Internal(total=total, scored=scored, excluded=excluded, errors=errors)


# --- invariants (spec section 6; number 7 is checked by re-running in analyse) ---------------


def _is_money(value: Any) -> bool:
    return _is_int(value) and value >= 0


def _invariant_failures(result: RunResult, internal: _Internal) -> list[int]:
    failed: set[int] = set()
    summary = result.summary
    statuses = [s.classification.status for s in internal.scored]

    # 1. every patient is scored, excluded or errored
    if internal.total != len(internal.scored) + len(internal.excluded) + len(internal.errors):
        failed.add(1)
    if (summary["patients_total"], summary["patients_scored"], summary["patients_excluded"],
        summary["patients_errored"]) != (internal.total, len(internal.scored), len(internal.excluded),
                                         len(internal.errors)):  # fmt: skip
        failed.add(1)

    # 2. dormant count, and the type rows plus unclassified add up to it
    dormant_rows = [r for r in result.patients if r.status == STATUS_DORMANT]
    unclassified = sum(1 for r in dormant_rows if r.primary_type is None)
    if not (summary["dormant_count"] == statuses.count(STATUS_DORMANT) == len(dormant_rows)):
        failed.add(2)
    if sum(t.patient_count for t in result.types) + summary["unclassified_dormant"] != summary["dormant_count"]:
        failed.add(2)
    if summary["unclassified_dormant"] != unclassified:
        failed.add(2)

    # 3. one status, at most one primary type, and the primary is among the matches
    for s in internal.scored:
        c = s.classification
        if c.status not in SCORED_STATUSES or len(set(c.matched_types)) != len(c.matched_types):
            failed.add(3)
        if c.primary_type is not None and c.primary_type not in c.matched_types:
            failed.add(3)
    for r in result.patients:
        if r.primary_type is not None and r.primary_type not in r.matched_types:
            failed.add(3)

    # 4. money is integer and not negative, low <= high, and the total is the sum of the rows
    new_rows = [t for t in result.types if t.revenue_kind == NEW]
    for t in result.types:
        if not all(
            _is_money(v) for v in (t.patient_count, t.basis_total_cents, t.revenue_low_cents, t.revenue_high_cents)
        ):
            failed.add(4)
        elif t.revenue_low_cents > t.revenue_high_cents:
            failed.add(4)
        if t.revenue_kind not in (NEW, RETENTION) or TYPE_KINDS.get(t.type_key) != t.revenue_kind:
            failed.add(4)
    for r in result.patients:
        if not _is_money(r.revenue_basis_cents) or not _is_money(r.total_spend_cents):
            failed.add(4)
    money_keys = ("new_revenue_low_cents", "new_revenue_high_cents", "retention_value_cents")
    if not all(_is_money(summary[k]) for k in money_keys) or not _is_money(summary.get("at_risk_revenue_cents", 0)):
        failed.add(4)
    if summary["new_revenue_low_cents"] != sum(t.revenue_low_cents for t in new_rows):
        failed.add(4)
    if summary["new_revenue_high_cents"] != sum(t.revenue_high_cents for t in new_rows):
        failed.add(4)

    # 5. scores are integers from 0 to 100 and patient ids are unique
    for r in result.patients:
        if not _is_int(r.likelihood_score) or not 0 <= r.likelihood_score <= 100:
            failed.add(5)
    if len({r.patient_id for r in result.patients}) != len(result.patients):
        failed.add(5)

    # 6. nobody with a future booking is dormant or at risk
    for s in internal.scored:
        if s.facts.has_future_booking and s.classification.status in (STATUS_DORMANT, STATUS_AT_RISK):
            failed.add(6)
    by_id = {s.facts.patient_id: s.facts for s in internal.scored}
    for r in result.patients:
        if by_id[r.patient_id].has_future_booking:
            failed.add(6)
    return sorted(failed)


# --- entry point -----------------------------------------------------------------------------


def analyse(
    facts: Iterable[PatientFacts],
    settings: ReactivationSettings,
    measured_rates: Mapping[str, MeasuredRate],
    past_responders: Mapping[uuid.UUID, PastResponse | str],
    previous_dormant_ids: Iterable[uuid.UUID] | None,
    now: datetime,
    tz_name: str,
    *,
    service_names: Mapping[uuid.UUID, str] | None = None,
    verify_determinism: bool = True,
) -> RunResult:
    """The result of one run, or `RunFailed` with an error code and nothing else.

    `past_responders` maps a patient to PastResponse; an absent patient was never contacted.
    `previous_dormant_ids` is the previous completed run's dormant patients, or None for a first run (also
    when that run's patient rows were purged). With `verify_determinism` the pure core runs a second time on
    the reversed input and the digests must match (invariant 7).
    """
    patients = list(facts)
    names = service_names or {}
    args = (settings, measured_rates, past_responders, previous_dormant_ids, now, tz_name, names)
    result, internal = _build(patients, *args)
    failed = _invariant_failures(result, internal)
    if verify_determinism:
        again, _ = _build(list(reversed(patients)), *args)
        if again.digest() != result.digest():
            failed = sorted({*failed, 7})
    if failed:
        raise RunFailed(ERR_INVARIANT, "invariants failed: " + ", ".join(str(n) for n in failed))
    return result
