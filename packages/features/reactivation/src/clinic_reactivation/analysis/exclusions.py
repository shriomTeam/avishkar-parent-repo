"""Who is left out before scoring (spec 4.11), and the spend percentile over who is left.

Pure: no database, no clock (``today`` is passed in). Used by ``facts.load_facts`` and by the
engine, so the cohort for the percentile is the same set the engine scores (D10).
"""

from __future__ import annotations

import json
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import replace
from datetime import date
from enum import StrEnum
from fractions import Fraction
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clinic_reactivation.analysis.facts import PatientFacts

MINOR_UNDER_YEARS = 18
DEFAULT_COHORT_MIN = 20

_TRUE_STRINGS = {"true", "yes", "y", "1"}
_FALSE_STRINGS = {"false", "no", "n", "0"}


class FlagValue(StrEnum):
    ABSENT = "absent"
    TRUE = "true"
    FALSE = "false"
    UNPARSABLE = "unparsable"  # present but not recognised: the patient is excluded (principle 9)


def parse_flag(raw: Any) -> FlagValue:
    """Strict parse of a ``patients.attributes`` exclusion flag already decoded from JSON.

    True: boolean true, or a case-insensitive string true/yes/y/1 (JSON number 1 included).
    False: boolean false, or false/no/n/0 (JSON number 0 included).
    Absent: key missing, JSON null, or a blank string. Anything else is unparsable.
    """
    if raw is None:
        return FlagValue.ABSENT
    if isinstance(raw, bool):
        return FlagValue.TRUE if raw else FlagValue.FALSE
    if isinstance(raw, int):
        return {1: FlagValue.TRUE, 0: FlagValue.FALSE}.get(raw, FlagValue.UNPARSABLE)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if not text:
            return FlagValue.ABSENT
        if text in _TRUE_STRINGS:
            return FlagValue.TRUE
        if text in _FALSE_STRINGS:
            return FlagValue.FALSE
    return FlagValue.UNPARSABLE


def parse_flag_json(raw_json_text: str | None) -> tuple[Any, FlagValue]:
    """The JSON text of one attribute (or None when the key is missing) -> (decoded, parsed)."""
    if raw_json_text is None:
        return None, FlagValue.ABSENT
    decoded = json.loads(raw_json_text)
    return decoded, parse_flag(decoded)


def age_years(date_of_birth: date, today: date) -> int:
    had_birthday = (today.month, today.day) >= (date_of_birth.month, date_of_birth.day)
    return today.year - date_of_birth.year - (0 if had_birthday else 1)


def dob_status(date_of_birth: date | None, today: date) -> tuple[bool, bool]:
    """(is_minor, invalid_dob). A missing DOB is not a minor; a DOB in the future is invalid and
    does not exclude the patient (spec 4.1)."""
    if date_of_birth is None:
        return False, False
    if date_of_birth > today:
        return False, True
    return age_years(date_of_birth, today) < MINOR_UNDER_YEARS, False


def exclusion_reasons(f: PatientFacts) -> tuple[str, ...]:
    """Every reason this patient is excluded, in a fixed order. Empty when the patient is scored."""
    reasons: list[str] = []
    if f.deceased is FlagValue.TRUE:
        reasons.append("deceased")
    if f.do_not_contact is FlagValue.TRUE:
        reasons.append("do_not_contact")
    if FlagValue.UNPARSABLE in (f.deceased, f.do_not_contact):
        reasons.append("unparsable_exclusion_flag")
    if f.is_minor:
        reasons.append("minor")
    return tuple(reasons)


def exclusion_reason(f: PatientFacts) -> str | None:
    """The single reason a patient is counted under: the first of ``exclusion_reasons``."""
    reasons = exclusion_reasons(f)
    return reasons[0] if reasons else None


def assign_spend_percentiles(
    facts: Sequence[PatientFacts], *, cohort_min: int = DEFAULT_COHORT_MIN
) -> list[PatientFacts]:
    """Fill ``spend_percentile`` (an exact Fraction in [0, 1]) for patients in the scored cohort.

    Cohort: at least one visit and not excluded. The value is (patients with strictly less spend)
    / (cohort size - 1), so equal spends share one value. With fewer than ``cohort_min`` in the
    cohort (D10) every patient gets None. Input order is preserved.
    """
    cohort = [f for f in facts if f.visit_count >= 1 and exclusion_reason(f) is None]
    if len(cohort) < cohort_min or len(cohort) < 2:
        return [replace(f, spend_percentile=None) for f in facts]
    spends = sorted(f.spend_cents for f in cohort)
    denominator = len(cohort) - 1
    in_cohort = {f.patient_id for f in cohort}
    return [
        replace(f, spend_percentile=Fraction(bisect_left(spends, f.spend_cents), denominator))
        if f.patient_id in in_cohort
        else replace(f, spend_percentile=None)
        for f in facts
    ]
