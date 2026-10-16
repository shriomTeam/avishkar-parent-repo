"""What a type could bring back, as a low-to-high range (spec 4.8, decisions D3, D4, D7).

Pure: no database, no clock. Money is integer cents; rates are Decimal. A type's figure is the sum of its
patients' basis cents times each rate, rounded once with ROUND_HALF_UP. A run total is the sum of the
rounded type rows, so it always equals them. Retention value (a prepaid balance, already paid) is never
added to new revenue.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

from clinic_reactivation.analysis.facts import PatientFacts
from clinic_reactivation.analysis.settings import ReactivationSettings

NEW = "new"
RETENTION = "retention"

TYPE_KINDS: dict[str, str] = {
    "lapsed_high_value": NEW,
    "churned_member": NEW,
    "consult_not_converted": NEW,
    "overdue_maintenance": NEW,
    "one_and_done": NEW,
    "unused_balance": RETENTION,
}

WILSON_Z = Decimal("1.96")
RATE_STEP = Decimal("0.0001")  # run_types.rate_low / rate_high are Numeric(5, 4)
ONE = Decimal(1)
ZERO = Decimal(0)

STATUS_DORMANT = "dormant"
STATUS_AT_RISK = "at_risk"

FLAG_NO_SPEND = "no_spend_recorded"
FLAG_FEE_MISSING = "membership_fee_missing"
FLAG_CONSULT_UNAVAILABLE = "consult_basis_unavailable"
FLAG_TICKET_FALLBACK = "ticket_fallback_to_patient_average"
FLAG_SPEND_FALLBACK = "ticket_fallback_to_spend"


# --- inputs ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MeasuredRate:
    booked: int
    contacted: int


@dataclass(frozen=True, slots=True)
class RevenueContext:
    median_first_treatment_ticket_cents: int | None


@dataclass(frozen=True, slots=True)
class RevenueInput:
    """One patient's classification, as revenue needs it (maps onto analysis/types.py's result)."""

    facts: PatientFacts
    status: str
    primary_type: str | None
    matched_types: tuple[str, ...] = ()


def half_up(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half up, in integers (both non-negative)."""
    return (2 * numerator + denominator) // (2 * denominator)


def practice_median_first_treatment_ticket(facts: Iterable[PatientFacts]) -> int | None:
    """Median first-treatment ticket over the given (scored) patients, for D3.

    Only positive tickets count: a ticket of 0 means the visit was fully refunded or unpaid, which is not
    a price. An even count averages the two middle values, half up.
    """
    values = sorted(
        f.first_treatment_ticket_cents
        for f in facts
        if f.first_treatment_ticket_cents is not None and f.first_treatment_ticket_cents > 0
    )
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else half_up(values[mid - 1] + values[mid], 2)


# --- basis -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Basis:
    cents: int
    kind: str
    flags: tuple[str, ...] = ()


def revenue_basis(type_key: str, facts: PatientFacts, context: RevenueContext, settings: ReactivationSettings) -> Basis:
    """What this patient would be worth if they came back as `type_key` (spec 4.7 and 4.4)."""
    if type_key not in TYPE_KINDS:
        raise ValueError(f"unknown patient type {type_key!r}")
    kind = TYPE_KINDS[type_key]
    average = facts.average_ticket_cents or 0

    if type_key == "lapsed_high_value":
        return _spend_basis(average, kind)

    if type_key == "churned_member":
        fee = facts.latest_membership_fee_cents
        if fee is None or fee <= 0:
            return Basis(0, kind, (FLAG_FEE_MISSING,))
        return Basis(fee * settings.types.churned_member.membership_months, kind)

    if type_key == "consult_not_converted":
        # D3: a recorded quote, else the practice's median first-treatment ticket. Never the consult fee.
        if facts.quoted_plan_cents is not None and facts.quoted_plan_cents > 0:
            return Basis(facts.quoted_plan_cents, kind)
        median = context.median_first_treatment_ticket_cents
        if median is not None and median > 0:
            return Basis(median, kind)
        return Basis(0, kind, (FLAG_CONSULT_UNAVAILABLE,))

    if type_key == "overdue_maintenance":
        total, days = facts.usual_service_ticket_total_cents, facts.usual_service_visit_days
        if total is not None and total > 0 and days > 0:
            return Basis(half_up(total, days), kind)
        return _spend_basis(average, kind, fallback=FLAG_TICKET_FALLBACK)

    if type_key == "one_and_done":
        visit = facts.first_visit_ticket_cents
        if visit is not None and visit > 0:
            return Basis(visit, kind)
        return _spend_basis(facts.spend_cents, kind, fallback=FLAG_SPEND_FALLBACK)

    if type_key == "unused_balance":
        return Basis(max(0, facts.prepaid_balance_cents), kind)

    raise AssertionError(f"patient type {type_key!r} has no basis rule")  # TYPE_KINDS and this function drifted


def _spend_basis(cents: int, kind: str, *, fallback: str | None = None) -> Basis:
    if cents <= 0:
        return Basis(0, kind, (FLAG_NO_SPEND,))
    return Basis(cents, kind, (fallback,) if fallback else ())


# --- rates -----------------------------------------------------------------------------------


def wilson(booked: int, contacted: int) -> tuple[Decimal, Decimal]:
    """Wilson 95% interval for booked / contacted (z = 1.96), clamped to 0 to 1."""
    if contacted < 1:
        raise ValueError("contacted must be at least 1")
    booked = max(0, min(booked, contacted))
    with localcontext() as ctx:
        ctx.prec = 40
        n, z2 = Decimal(contacted), WILSON_Z * WILSON_Z
        p = Decimal(booked) / n
        denominator = 1 + z2 / n
        centre = (p + z2 / (2 * n)) / denominator
        margin = WILSON_Z * (p * (1 - p) / n + z2 / (4 * n * n)).sqrt() / denominator
        return max(ZERO, centre - margin), min(ONE, centre + margin)


@dataclass(frozen=True, slots=True)
class RateRange:
    low: Decimal
    high: Decimal
    source: Literal["assumed", "measured"]


def _quantised(low: Decimal, high: Decimal, source: Literal["assumed", "measured"]) -> RateRange:
    """Stored rates are 4 decimal places, so round them first (low down, high up, never narrower than
    the interval) and multiply by what is stored: the run can be re-derived from its own rows."""
    low = min(max(low.quantize(RATE_STEP, rounding=ROUND_FLOOR), ZERO), ONE)
    high = min(max(high.quantize(RATE_STEP, rounding=ROUND_CEILING), ZERO), ONE)
    return RateRange(min(low, high), max(low, high), source)


def rate_range(type_key: str, measured: Mapping[str, MeasuredRate] | None, settings: ReactivationSettings) -> RateRange:
    """The clinic's real rate once at least `min_sample` patients of this type were contacted, else the
    assumed range. A retention type (a balance already paid) has no return rate: 1.0 to 1.0."""
    if TYPE_KINDS[type_key] == RETENTION:
        return RateRange(ONE, ONE, "assumed")
    sample = (measured or {}).get(type_key)
    if sample is not None and sample.contacted >= settings.revenue.min_sample:
        low, high = wilson(sample.booked, sample.contacted)
        return _quantised(low, high, "measured")
    return _quantised(Decimal(str(settings.revenue.rate_low)), Decimal(str(settings.revenue.rate_high)), "assumed")


# --- per type and per run --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypeRevenue:
    type_key: str
    patient_count: int
    basis_total_cents: int
    rate_low: Decimal
    rate_high: Decimal
    rate_source: str
    revenue_low_cents: int
    revenue_high_cents: int
    revenue_kind: str


def _money(cents: int, rate: Decimal) -> int:
    with localcontext() as ctx:
        ctx.prec = 40
        return int((Decimal(cents) * rate).quantize(ONE, rounding=ROUND_HALF_UP))


def type_revenue(type_key: str, bases: Sequence[int], rate: RateRange) -> TypeRevenue:
    """Sum the basis cents first, multiply by each rate, round once half up."""
    if any(b < 0 for b in bases):
        raise ValueError("a revenue basis cannot be negative")
    total = sum(bases)
    low, high = _money(total, rate.low), _money(total, rate.high)
    return TypeRevenue(
        type_key=type_key,
        patient_count=len(bases),
        basis_total_cents=total,
        rate_low=rate.low,
        rate_high=rate.high,
        rate_source=rate.source,
        revenue_low_cents=min(low, high),
        revenue_high_cents=max(low, high),
        revenue_kind=TYPE_KINDS[type_key],
    )


@dataclass(frozen=True, slots=True)
class RevenueSummary:
    rows: tuple[TypeRevenue, ...]
    new_low_cents: int  # sum of the rounded new-revenue rows
    new_high_cents: int
    retention_cents: int  # D4: every dormant patient's prepaid balance, shown apart from new revenue
    at_risk_revenue_cents: int  # D7: average ticket of at-risk patients, never multiplied or added
    zero_basis_patients: int
    flag_counts: dict[str, int] = field(default_factory=dict)


def at_risk_exposure(inputs: Iterable[RevenueInput]) -> int:
    return sum(i.facts.average_ticket_cents or 0 for i in inputs if i.status == STATUS_AT_RISK)


def summarise_revenue(
    inputs: Iterable[RevenueInput],
    context: RevenueContext,
    settings: ReactivationSettings,
    measured: Mapping[str, MeasuredRate] | None = None,
) -> RevenueSummary:
    """One row per enabled type (by priority), by primary type, plus the separate figures."""
    entries = list(inputs)
    enabled = sorted(
        (key for key in TYPE_KINDS if getattr(settings.types, key).enabled),
        key=lambda key: (getattr(settings.types, key).priority, key),
    )
    bases: dict[str, list[int]] = {key: [] for key in enabled}
    flags: dict[str, int] = {}
    zero_basis = 0
    for entry in entries:
        if entry.status != STATUS_DORMANT or entry.primary_type not in bases:
            continue
        basis = revenue_basis(entry.primary_type, entry.facts, context, settings)
        bases[entry.primary_type].append(basis.cents)
        for flag in basis.flags:
            flags[flag] = flags.get(flag, 0) + 1
        if FLAG_NO_SPEND in basis.flags:
            zero_basis += 1

    rows = tuple(type_revenue(key, bases[key], rate_range(key, measured, settings)) for key in enabled)
    new_rows = [row for row in rows if row.revenue_kind == NEW]
    retention = sum(
        max(0, e.facts.prepaid_balance_cents)
        for e in entries
        if e.status == STATUS_DORMANT and "unused_balance" in e.matched_types
    )
    return RevenueSummary(
        rows=rows,
        new_low_cents=sum(row.revenue_low_cents for row in new_rows),
        new_high_cents=sum(row.revenue_high_cents for row in new_rows),
        retention_cents=retention,
        at_risk_revenue_cents=at_risk_exposure(entries),
        zero_basis_patients=zero_basis,
        flag_counts=dict(sorted(flags.items())),
    )
