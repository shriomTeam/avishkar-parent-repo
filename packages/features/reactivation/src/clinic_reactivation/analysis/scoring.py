"""Likelihood to return, 0 to 100 (spec 4.9), and the order results are shown in.

Pure. Every term is an exact fraction, the weighted sum is an exact rational, and the one rounding step is
a Decimal ROUND_HALF_UP at the end, so a score on a half point never depends on decimal precision.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from enum import StrEnum
from fractions import Fraction

from clinic_reactivation.analysis.facts import PatientFacts

WEIGHT_RECENCY = Fraction(40, 100)
WEIGHT_FREQUENCY = Fraction(25, 100)
WEIGHT_SPEND = Fraction(20, 100)
WEIGHT_RESPONSE = Fraction(15, 100)

FREQUENCY_CAP_VISITS = 10
RECENCY_RANGE = Fraction(3)  # R falls from 1 at ratio 1 to 0 at ratio 4
UNKNOWN_SPEND_TERM = Fraction(1, 2)  # D10: no percentile for a tiny cohort


class PastResponse(StrEnum):
    BOOKED = "booked"  # booked after a past campaign
    NOT_BOOKED = "not_booked"  # contacted by a past campaign and did not book
    NEVER = "never"  # never contacted


_RESPONSE_TERM = {
    PastResponse.BOOKED: Fraction(1),
    PastResponse.NOT_BOOKED: Fraction(0),
    PastResponse.NEVER: Fraction(1, 2),
}


@dataclass(frozen=True, slots=True)
class RatioInputs:
    """Days since the last visit against the rebooking interval in force for this patient."""

    days_since_last_visit: int
    interval_days: int

    def __post_init__(self) -> None:
        if self.interval_days < 1:
            raise ValueError("interval_days must be at least 1")
        if self.days_since_last_visit < 0:
            raise ValueError("days_since_last_visit cannot be negative")


@dataclass(frozen=True, slots=True)
class ScoreTerms:
    recency: Fraction  # R
    frequency: Fraction  # F
    spend: Fraction  # M
    response: Fraction  # P


def _clamp01(x: Fraction) -> Fraction:
    return min(max(x, Fraction(0)), Fraction(1))


def score_terms(facts: PatientFacts, ratio_inputs: RatioInputs, past_response: PastResponse) -> ScoreTerms:
    ratio = Fraction(ratio_inputs.days_since_last_visit, ratio_inputs.interval_days)
    return ScoreTerms(
        recency=_clamp01(1 - (ratio - 1) / RECENCY_RANGE),
        frequency=Fraction(min(facts.visit_count, FREQUENCY_CAP_VISITS), FREQUENCY_CAP_VISITS),
        spend=UNKNOWN_SPEND_TERM if facts.spend_percentile is None else _clamp01(facts.spend_percentile),
        response=_RESPONSE_TERM[PastResponse(past_response)],
    )


def likelihood_score(facts: PatientFacts, ratio_inputs: RatioInputs, past_response: PastResponse) -> int:
    """round_half_up(100 * (0.40 R + 0.25 F + 0.20 M + 0.15 P)), clamped to 0 to 100, as an int."""
    t = score_terms(facts, ratio_inputs, past_response)
    exact = 100 * (
        WEIGHT_RECENCY * t.recency
        + WEIGHT_FREQUENCY * t.frequency
        + WEIGHT_SPEND * t.spend
        + WEIGHT_RESPONSE * t.response
    )
    with localcontext() as ctx:
        ctx.prec = 50
        rounded = (Decimal(exact.numerator) / Decimal(exact.denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return max(0, min(100, int(rounded)))


def ordering_key(score: int, spend_cents: int, patient_id: uuid.UUID) -> tuple[int, int, int]:
    """Sort ascending by this key: score descending, then spend descending, then patient id."""
    return (-score, -spend_cents, patient_id.int)
