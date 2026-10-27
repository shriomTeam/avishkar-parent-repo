"""Who is dormant or at risk, and which patient types they match (spec 4.5 to 4.7, D2, D6, D10, D11).

Pure: no database, no clock (``now`` and the clinic timezone are passed in). Every threshold is decided in
integers: a ratio threshold is an exact fraction (from its decimal string) and is compared by
cross-multiplication, so 0.7 x 10 days is exactly 7 and never 7.000000000000001. Ratios printed in reasons
are for people only and decide nothing.

A patient is dormant when they have no future booking and either the general rule holds
(``days > min_days_since_visit`` or ``days > interval``) or an enabled type with its own entry rule matches
(lapsed_high_value, churned_member with an end date, consult_not_converted, one_and_done). overdue_maintenance,
lapsed_regular and a churned_member with no end date also need the general rule, and unused_balance only needs
the patient to be dormant by any route; none of those four can make a patient dormant by itself. A future
booking overrides every route.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from fractions import Fraction
from zoneinfo import ZoneInfo

from clinic_reactivation.analysis.facts import PatientFacts
from clinic_reactivation.analysis.settings import ReactivationSettings, ratio_fraction

STATUS_DORMANT = "dormant"
STATUS_AT_RISK = "at_risk"
STATUS_ACTIVE = "active"  # scored, neither dormant nor at risk (this includes anyone with a future booking)
STATUS_NO_VISITS = "no_visits"  # nothing to judge; the engine reports these as no_completed_visits

TYPE_KEYS = (
    "lapsed_high_value",
    "churned_member",
    "consult_not_converted",
    "overdue_maintenance",
    "one_and_done",
    "lapsed_regular",
    "unused_balance",
)
CHURNED_STATUSES = frozenset({"cancelled", "lapsed", "expired"})
KNOWN_MEMBERSHIP_STATUSES = CHURNED_STATUSES | {"active"}
FALLBACK_REBOOKING_DAYS = 120  # only used if the settings default is itself unusable

FLAG_INVALID_INTERVAL = "invalid_rebooking_interval"
FLAG_MISSING_SERVICE = "missing_service_on_visits"
FLAG_UNKNOWN_MEMBERSHIP = "unknown_membership_status"


# --- results ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IntervalChoice:
    days: int
    source: str  # service, category or default
    invalid_levels_skipped: int  # a configured value that was 0, negative or not a number


@dataclass(frozen=True, slots=True)
class Classification:
    patient_id: uuid.UUID
    status: str
    primary_type: str | None
    matched_types: tuple[str, ...]  # by priority, then type key
    reasons: tuple[str, ...]  # plain English
    days_since_last_visit: int | None
    interval_days: int
    interval_source: str
    skipped_types: tuple[str, ...] = ()  # for example lapsed_high_value:cohort_too_small
    quality_flags: tuple[str, ...] = ()
    type_reasons: tuple[str, ...] = ()  # only the matched types' sentences, in `matched_types` order


# --- small pure helpers ----------------------------------------------------------------------


def local_today(now: datetime, tz_name: str) -> date:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(ZoneInfo(tz_name)).date()


def days_since_last_visit(facts: PatientFacts, today: date) -> int | None:
    """Whole clinic-local calendar days (spec 4.1), None for a patient with no visit."""
    return None if facts.last_visit_day is None else (today - facts.last_visit_day).days


def _usable(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def interval_for(facts: PatientFacts, settings: ReactivationSettings) -> IntervalChoice:
    """Service interval, else category interval (case-insensitive, trimmed), else the default (spec 4.5).

    A level with no entry is simply skipped. A level whose configured value is 0, negative or not a number
    is skipped too and counted, so the interval used is never below 1.
    """
    rules = settings.dormant
    skipped = 0
    service = facts.usual_service_id
    if service is not None and service in rules.rebooking_days_by_service:
        value = rules.rebooking_days_by_service[service]
        if _usable(value):
            return IntervalChoice(value, "service", skipped)
        skipped += 1
    category = facts.usual_service_category_norm
    if category is not None:
        by_category: dict[str, object] = {}
        for key in sorted(rules.rebooking_days_by_category):
            by_category.setdefault(key.strip().lower(), rules.rebooking_days_by_category[key])
        if category in by_category:
            value = by_category[category]
            if _usable(value):
                return IntervalChoice(int(value), "category", skipped)  # type: ignore[arg-type]
            skipped += 1
    if _usable(rules.default_rebooking_days):
        return IntervalChoice(rules.default_rebooking_days, "default", skipped)
    return IntervalChoice(FALLBACK_REBOOKING_DAYS, "default", skipped + 1)


def _at_least(days: int, interval: int, ratio: Fraction) -> bool:
    """days / interval >= ratio, by cross-multiplication."""
    return days * ratio.denominator >= ratio.numerator * interval


def _above(days: int, interval: int, ratio: Fraction) -> bool:
    return days * ratio.denominator > ratio.numerator * interval


def _below(days: int, interval: int, ratio: Fraction) -> bool:
    return days * ratio.denominator < ratio.numerator * interval


def _shown_ratio(days: int, interval: int) -> str:
    return f"{days / interval:.1f}"  # for people only; never used to decide anything


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


# --- the seven type entry rules (spec 4.7) -----------------------------------------------------
# Each returns a plain-English reason when the type's entry rule and its extra requirements hold, else None.
# Whether the patient must also be dormant by the general rule is decided by the caller.


def _lapsed_high_value(f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date) -> str | None:
    rule = s.types.lapsed_high_value
    by_percentile = f.spend_percentile is not None and f.spend_percentile >= Fraction(rule.spend_percentile_min, 100)
    # The dollar cutoff needs no cohort, so it still applies when the cohort is too small for a percentile (D10).
    # The engine then reports the type as available; skipped_types still records that the percentile rule was skipped.
    by_dollars = rule.spend_cents_min is not None and f.spend_cents > rule.spend_cents_min
    if not (by_percentile or by_dollars):
        return None
    if not _at_least(days, interval, ratio_fraction(rule.overdue_ratio_min)):
        return None
    if by_percentile:
        return (
            f"In the top {100 - rule.spend_percentile_min}% of patients by spend and {days} days since the last visit, "
            f"{_shown_ratio(days, interval)} times the usual {interval} day interval."
        )
    return (
        f"Spent more than {_money(rule.spend_cents_min)} in total and {days} days since the last visit, "
        f"{_shown_ratio(days, interval)} times the usual {interval} day interval."
    )


def _churned_member(f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date) -> str | None:
    status = f.latest_membership_status
    if status not in CHURNED_STATUSES or f.has_active_membership:
        return None  # an unknown status is never treated as churned
    end = f.latest_membership_end
    if end is not None and f.last_visit_day is not None and f.last_visit_day > end:
        return None  # they have been back since the membership ended
    when = f" on {end.isoformat()}" if end is not None else ""
    since = " and they have not visited since" if end is not None else ""
    return f"Membership {status}{when}, no active membership{since}."


def _consult_not_converted(
    f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date
) -> str | None:
    window = s.types.consult_not_converted.conversion_window_days
    if f.latest_consult_day is None or f.converted_within_window is not False:
        return None
    age = (today - f.latest_consult_day).days
    if age <= window:
        return None  # day 60 is not yet "more than 60 days"
    return f"Had a consult {age} days ago and no treatment visit in the {window} days after it."


def _overdue_maintenance(f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date) -> str | None:
    rule = s.types.overdue_maintenance
    if f.usual_service_visit_days < rule.min_visits:
        return None
    if not (
        _above(days, interval, ratio_fraction(rule.overdue_ratio_min))
        and _below(days, interval, ratio_fraction(rule.overdue_ratio_max))
    ):
        return None
    return (
        f"Has come {f.usual_service_visit_days} times for their usual service and is overdue: {days} days since "
        f"the last visit against a {interval} day interval."
    )


def _one_and_done(f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date) -> str | None:
    if f.visit_count != 1 or days <= s.types.one_and_done.min_days_since_visit:
        return None
    return f"Only one visit, {days} days ago."


def _lapsed_regular(f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date) -> str | None:
    if f.visit_count < 2:
        return None  # the caller adds the general-rule requirement; this type never creates dormancy (D13)
    return (
        f"Repeat patient with {f.visit_count} visits, {days} days since the last visit "
        f"against a {interval} day interval."
    )


def _unused_balance(f: PatientFacts, s: ReactivationSettings, days: int, interval: int, today: date) -> str | None:
    if f.prepaid_balance_cents <= 0:
        return None
    return f"Has {_money(f.prepaid_balance_cents)} of prepaid balance unused."


_ENTRY = {
    "lapsed_high_value": _lapsed_high_value,
    "churned_member": _churned_member,
    "consult_not_converted": _consult_not_converted,
    "overdue_maintenance": _overdue_maintenance,
    "one_and_done": _one_and_done,
    "lapsed_regular": _lapsed_regular,
    "unused_balance": _unused_balance,
}
_OWN_ENTRY = ("lapsed_high_value", "consult_not_converted", "one_and_done")  # create dormancy by themselves


# --- classification --------------------------------------------------------------------------


def _quality_flags(f: PatientFacts, interval: IntervalChoice) -> tuple[str, ...]:
    flags = []
    if interval.invalid_levels_skipped:
        flags.append(FLAG_INVALID_INTERVAL)
    if f.visit_count >= 1 and f.usual_service_id is None:
        flags.append(FLAG_MISSING_SERVICE)
    if f.unknown_membership_status:
        flags.append(FLAG_UNKNOWN_MEMBERSHIP)
    return tuple(sorted(flags))


def classify(facts: PatientFacts, settings: ReactivationSettings, now: datetime, tz_name: str) -> Classification:
    today = local_today(now, tz_name)
    interval = interval_for(facts, settings)
    flags = _quality_flags(facts, interval)
    days = days_since_last_visit(facts, today)

    def result(status, reasons, primary=None, matched=(), skipped=(), type_reasons=()):
        return Classification(
            patient_id=facts.patient_id,
            status=status,
            primary_type=primary,
            matched_types=tuple(matched),
            reasons=tuple(reasons),
            days_since_last_visit=days,
            interval_days=interval.days,
            interval_source=interval.source,
            skipped_types=tuple(skipped),
            quality_flags=flags,
            type_reasons=tuple(type_reasons),
        )

    if facts.visit_count < 1 or days is None:
        return result(STATUS_NO_VISITS, ["No completed visits."])
    if facts.has_future_booking:
        return result(STATUS_ACTIVE, ["Has an upcoming booking."])  # overrides every route

    enabled = {key for key in TYPE_KEYS if getattr(settings.types, key).enabled}
    skipped = (
        ["lapsed_high_value:cohort_too_small"]
        if "lapsed_high_value" in enabled and facts.spend_percentile is None
        else []
    )
    min_days = settings.dormant.min_days_since_visit
    general = days > min_days or days > interval.days

    reasons: dict[str, str] = {}
    for key in enabled:
        reason = _ENTRY[key](facts, settings, days, interval.days, today)
        if reason is not None:
            reasons[key] = reason

    own = {key for key in _OWN_ENTRY if key in reasons}
    if "churned_member" in reasons and facts.latest_membership_end is not None:
        own.add("churned_member")  # with an end date it is its own entry rule; without one it needs the general rule
    dormant = general or bool(own)

    if not dormant:
        if days <= interval.days and _at_least(days, interval.days, ratio_fraction(settings.dormant.at_risk_ratio_min)):
            return result(
                STATUS_AT_RISK,
                [
                    f"Approaching their usual rebooking time: {days} days since the last visit against a "
                    f"{interval.days} day interval."
                ],
                skipped=skipped,
            )
        return result(STATUS_ACTIVE, [f"Visited {days} days ago; not due yet."], skipped=skipped)

    matched = set(own)
    if general:
        matched |= {key for key in ("overdue_maintenance", "lapsed_regular", "churned_member") if key in reasons}
    if "unused_balance" in reasons:
        matched.add("unused_balance")  # dormant by any route, never creates dormancy
    ordered = sorted(matched, key=lambda key: (getattr(settings.types, key).priority, key))

    lead = []
    if days > interval.days:
        lead.append(
            f"{days} days since the last visit, more than the usual {interval.days} day interval ({interval.source})."
        )
    elif days > min_days:
        lead.append(f"{days} days since the last visit, more than the {min_days} day limit.")
    detail = [reasons[key] for key in ordered]
    if not ordered:
        detail.append("Dormant, but matches none of the enabled patient types.")
    return result(
        STATUS_DORMANT,
        lead + detail,
        ordered[0] if ordered else None,
        ordered,
        skipped,
        [reasons[key] for key in ordered],
    )


def classify_all(
    facts: Iterable[PatientFacts], settings: ReactivationSettings, now: datetime, tz_name: str
) -> list[Classification]:
    """Output is ordered by patient id, so the input order never changes the result."""
    return sorted((classify(f, settings, now, tz_name) for f in facts), key=lambda c: c.patient_id.int)


def is_dormant(facts: PatientFacts, settings: ReactivationSettings, now: datetime, tz_name: str) -> bool:
    return classify(facts, settings, now, tz_name).status == STATUS_DORMANT


def is_at_risk(facts: PatientFacts, settings: ReactivationSettings, now: datetime, tz_name: str) -> bool:
    return classify(facts, settings, now, tz_name).status == STATUS_AT_RISK
