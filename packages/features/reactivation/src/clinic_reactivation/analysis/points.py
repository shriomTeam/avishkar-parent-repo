"""The optional analysis points shown with each patient (spec 4.10), and what data the run could see.

Pure: ``now`` and the clinic timezone are passed in. A point switched off in settings is absent from the
output, never null. A point that is switched on but cannot be worked out says so with a ``reason``.
"""

from __future__ import annotations

import calendar
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from clinic_reactivation.analysis.facts import PatientFacts, reachable_from
from clinic_reactivation.analysis.settings import ReactivationSettings

STATUS_DORMANT = "dormant"
STATUS_AT_RISK = "at_risk"
STATUS_ACTIVE = "active"

BEST_TIME_MIN_VISITS = 3
BAND_HOURS = 3
SEASON_MIN_YEARS = 2


class Change(StrEnum):
    FIRST_RUN = "first_run"
    NEW = "new"
    UNCHANGED = "unchanged"
    RETURNED = "returned_since_last"


@dataclass(frozen=True, slots=True)
class PreviousRun:
    """The previous completed run's dormant patients. A run whose patient rows were purged is passed as
    None, which counts as no previous run."""

    dormant_ids: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class ChangeCounts:
    first_run: bool
    new: int  # dormant now, not dormant before
    unchanged: int  # dormant now and before
    returned_since_last: int  # dormant before, scored now and no longer dormant


# --- single points ---------------------------------------------------------------------------


def best_offer(facts: PatientFacts, primary_type: str | None) -> dict[str, Any]:
    if primary_type == "consult_not_converted":
        service, source = facts.latest_consult_service_id, "consulted_service"
    else:
        service, source = facts.usual_service_id, "usual_service"
    if service is None:
        return {"service_id": None, "source": None, "reason": "no_service_on_record"}
    return {"service_id": service, "source": source}


def _mode_preferring_recent(values: list[int]) -> int:
    """The most common value; a tie goes to the value of the most recent visit (the list is oldest first)."""
    counts = Counter(values)
    top = max(counts.values())
    tied = {v for v, c in counts.items() if c == top}
    return next(v for v in reversed(values) if v in tied)


def best_time(facts: PatientFacts, tz_name: str) -> dict[str, Any]:
    """Most common weekday (Monday is 0) and, separately, most common 3-hour band (hour // 3), in the
    clinic's timezone."""
    if len(facts.visit_starts) < BEST_TIME_MIN_VISITS:
        return {"weekday": None, "band": None, "reason": "fewer_than_3_visits"}
    tz = ZoneInfo(tz_name)
    local = [start.astimezone(tz) for start in facts.visit_starts]
    return {
        "weekday": _mode_preferring_recent([d.weekday() for d in local]),
        "band": _mode_preferring_recent([d.hour // BAND_HOURS for d in local]),
        "visits_used": len(local),
    }


def reachable(facts: PatientFacts) -> dict[str, Any]:
    r = reachable_from(facts.ingredients)
    return {"sms": r.sms, "email": r.email, "either": r.either}


def provider_continuity(facts: PatientFacts) -> dict[str, Any]:
    """Active, inactive or unknown. No usual provider, or a provider with no staff record (staff is not
    imported yet), is unknown."""
    if facts.usual_provider_id is None or facts.provider_staff_active is None:
        return {"status": "unknown"}
    return {"status": "active" if facts.provider_staff_active else "inactive"}


def _season_year(visit: date, centre_month: int) -> int:
    """A December visit belongs to the following January's season, a January visit to the previous
    December's, so one winter is one season year."""
    if centre_month == 1 and visit.month == 12:
        return visit.year + 1
    if centre_month == 12 and visit.month == 1:
        return visit.year - 1
    return visit.year


def _window(centre_month: int, season_year: int) -> tuple[date, date]:
    """First day of the month before the centre month to the last day of the month after it."""
    start = date(season_year - 1, 12, 1) if centre_month == 1 else date(season_year, centre_month - 1, 1)
    end_year, end_month = (season_year + 1, 1) if centre_month == 12 else (season_year, centre_month + 1)
    return start, date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])


def seasonality(facts: PatientFacts, now: datetime, tz_name: str, window_days: int) -> dict[str, Any]:
    """Completed visits within one month either side of the same calendar month, in at least 2 distinct
    season years, with that window under way or starting within `window_days` of today."""
    today = now.astimezone(ZoneInfo(tz_name)).date()
    horizon = today + timedelta(days=window_days)
    candidates: list[tuple[int, date, int, date, int]] = []
    pattern_found = False
    for centre in range(1, 13):
        months = {(centre - 2) % 12 + 1, centre, centre % 12 + 1}
        in_season = [d for d in facts.visit_days if d.month in months]
        years = {_season_year(d, centre) for d in in_season}
        if len(years) < SEASON_MIN_YEARS:
            continue
        pattern_found = True
        for year in range(today.year - 1, today.year + 2):
            start, end = _window(centre, year)
            if end >= today and start <= horizon:
                candidates.append((-len(in_season), start, centre, end, len(years)))
    if not pattern_found:
        return {"applies": False, "reason": "fewer_than_2_years"}
    if not candidates:
        return {"applies": False, "reason": "window_not_near"}
    _, start, centre, end, years = min(candidates)
    return {
        "applies": True,
        "month": centre,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "years": years,
    }


def change_since_last(patient_id: uuid.UUID, status: str, previous: PreviousRun | None) -> str:
    """First run for everyone when there is no previous run (D8), else against its dormant patients."""
    if previous is None:
        return Change.FIRST_RUN
    was_dormant = patient_id in previous.dormant_ids
    if status == STATUS_DORMANT:
        return Change.UNCHANGED if was_dormant else Change.NEW
    return Change.RETURNED if was_dormant else Change.NEW


def change_counts(previous: PreviousRun | None, statuses: Mapping[uuid.UUID, str]) -> ChangeCounts:
    """Run-level tiles. `statuses` holds every patient who was scored (dormant, at_risk or active).
    A patient now excluded or errored is absent, so has not come back."""
    if previous is None:
        return ChangeCounts(first_run=True, new=0, unchanged=0, returned_since_last=0)
    dormant_now = {pid for pid, status in statuses.items() if status == STATUS_DORMANT}
    returned = [pid for pid in previous.dormant_ids if statuses.get(pid) in (STATUS_AT_RISK, STATUS_ACTIVE)]
    return ChangeCounts(
        first_run=False,
        new=len(dormant_now - previous.dormant_ids),
        unchanged=len(dormant_now & previous.dormant_ids),
        returned_since_last=len(returned),
    )


def revenue_at_risk(facts: PatientFacts, status: str) -> dict[str, Any] | None:
    """D7: an at-risk patient's average ticket, shown on its own and never multiplied or added to anything.
    Not applicable (None) to anyone who is not at risk."""
    if status != STATUS_AT_RISK:
        return None
    return {"cents": facts.average_ticket_cents or 0}


# --- all enabled points for one patient ------------------------------------------------------


def analysis_points(
    facts: PatientFacts,
    status: str,
    primary_type: str | None,
    settings: ReactivationSettings,
    now: datetime,
    tz_name: str,
    previous: PreviousRun | None,
) -> dict[str, Any]:
    """Only the points switched on in settings (and, for revenue_at_risk, only for at-risk patients)."""
    on = settings.points
    out: dict[str, Any] = {}
    if on.best_offer:
        out["best_offer"] = best_offer(facts, primary_type)
    if on.best_time:
        out["best_time"] = best_time(facts, tz_name)
    if on.reachable:
        out["reachable"] = reachable(facts)
    if on.provider_continuity:
        out["provider_continuity"] = provider_continuity(facts)
    if on.seasonality:
        out["seasonality"] = seasonality(facts, now, tz_name, settings.limits.seasonality_window_days)
    if on.change_since_last:
        out["change_since_last"] = {"change": change_since_last(facts.patient_id, status, previous)}
    if on.revenue_at_risk and (risk := revenue_at_risk(facts, status)) is not None:
        out["revenue_at_risk"] = risk
    return out


def data_available(facts: Iterable[PatientFacts]) -> dict[str, bool]:
    """Whether each source had any data at all, so an empty source is reported as not available, not as
    zero patients (spec section 3 and 5)."""
    seen = {"staff": False, "memberships": False, "consents": False, "services": False}
    for f in facts:
        seen["staff"] |= f.provider_staff_active is not None
        seen["memberships"] |= f.membership_rows > 0
        seen["consents"] |= f.ingredients.consent_sms is not None or f.ingredients.consent_email is not None
        seen["services"] |= f.usual_service_id is not None
    return seen
