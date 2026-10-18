import random
import uuid
from fractions import Fraction

import pytest
from builders import blank

from clinic_reactivation.analysis.scoring import (
    PastResponse,
    RatioInputs,
    likelihood_score,
    ordering_key,
    score_terms,
)

F = Fraction


def terms(*, days=100, interval=100, visits=5, percentile=F(1, 2), response=PastResponse.NEVER):
    return score_terms(blank(visit_count=visits, spend_percentile=percentile), RatioInputs(days, interval), response)


def score(*, days=100, interval=100, visits=5, percentile=F(1, 2), response=PastResponse.NEVER) -> int:
    return likelihood_score(
        blank(visit_count=visits, spend_percentile=percentile), RatioInputs(days, interval), response
    )


# --- each term at its boundaries -------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "interval", "expected"),
    [
        (0, 100, F(1)),
        (50, 100, F(1)),  # at risk: not overdue yet
        (100, 100, F(1)),  # exactly on the interval
        (101, 100, F(1) - F(1, 300)),
        (150, 100, F(5, 6)),
        (200, 100, F(2, 3)),
        (399, 100, F(1, 300)),
        (400, 100, F(0)),  # ratio 4 and beyond
        (1000, 100, F(0)),
    ],
)
def test_recency_term(days, interval, expected):
    assert terms(days=days, interval=interval).recency == expected


@pytest.mark.parametrize(
    ("visits", "expected"), [(0, F(0)), (1, F(1, 10)), (9, F(9, 10)), (10, F(1)), (11, F(1)), (80, F(1))]
)
def test_frequency_term_is_capped_at_ten_visits(visits, expected):
    assert terms(visits=visits).frequency == expected


def test_spend_term_is_the_percentile_and_half_when_the_cohort_was_too_small():
    assert terms(percentile=F(0)).spend == 0
    assert terms(percentile=F(79, 100)).spend == F(79, 100)
    assert terms(percentile=F(1)).spend == 1
    assert terms(percentile=None).spend == F(1, 2)  # D10


def test_response_term():
    assert terms(response=PastResponse.BOOKED).response == 1
    assert terms(response=PastResponse.NOT_BOOKED).response == 0
    assert terms(response=PastResponse.NEVER).response == F(1, 2)  # never contacted
    assert terms(response="booked").response == 1  # plain strings are accepted


def test_the_inputs_are_checked():
    with pytest.raises(ValueError, match="interval_days"):
        RatioInputs(10, 0)
    with pytest.raises(ValueError, match="negative"):
        RatioInputs(-1, 100)
    with pytest.raises(ValueError):
        terms(response="maybe")


# --- the score -------------------------------------------------------------------------------


def test_the_best_and_worst_patients_score_100_and_0():
    assert score(days=100, interval=100, visits=10, percentile=F(1), response=PastResponse.BOOKED) == 100
    assert score(days=400, interval=100, visits=0, percentile=F(0), response=PastResponse.NOT_BOOKED) == 0


def test_a_tiny_cohort_scores_with_spend_half_and_a_never_contacted_patient_with_response_half():
    # R=1 (40) + F=1 (25) + M=0.5 (10) + P=0.5 (7.5) = 82.5, which rounds up
    assert score(visits=10, percentile=None, response=PastResponse.NEVER) == 83
    # with a real percentile of 0.5 the result is the same, so None really means 0.5
    assert score(visits=10, percentile=F(1, 2), response=PastResponse.NEVER) == 83


def test_a_half_point_rounds_up_not_to_even():
    # R=1 (40) + F=1/10 (2.5) + M=0 + P=0 = 42.5: half-even would give 42
    assert score(visits=1, percentile=F(0), response=PastResponse.NOT_BOOKED) == 43
    # and 99.5 -> 100 while 99.33 -> 99, at the exact edge of the recency term
    top = dict(visits=10, percentile=F(1), response=PastResponse.BOOKED)
    assert score(days=83, interval=80, **top) == 100  # 60 + 40 * 79/80 = 99.5
    assert score(days=84, interval=80, **top) == 99  # 60 + 40 * 59/60 = 99.33


def test_rounding_is_exact_on_either_side_of_a_half_point():
    # 100 * (0.2 M) with M = 2.5/100 ... walk the percentile across x.5 boundaries exactly
    base = dict(days=100, interval=100, visits=0, response=PastResponse.NOT_BOOKED)  # 40 from recency alone
    assert score(percentile=F(2, 40), **base) == 41  # 40 + 20/20 -> 40 + 1.0
    assert score(percentile=F(1, 40), **base) == 41  # 40.5 rounds up
    assert score(percentile=F(1, 40) - F(1, 10**9), **base) == 40  # just under 40.5


def test_every_score_is_an_integer_from_0_to_100():
    rng = random.Random(42)
    seen = set()
    for _ in range(3000):
        value = score(
            days=rng.randint(0, 1200),
            interval=rng.randint(1, 400),
            visits=rng.randint(0, 15),
            percentile=rng.choice([None, F(rng.randint(0, 100), 100)]),
            response=rng.choice(list(PastResponse)),
        )
        assert type(value) is int and 0 <= value <= 100
        seen.add(value)
    assert len(seen) > 40  # it really spreads over the range


def test_the_score_never_falls_when_a_patient_is_more_recent_or_more_loyal():
    for days in range(0, 500, 25):
        assert score(days=days) >= score(days=days + 25)
    for visits in range(0, 10):
        assert score(visits=visits) <= score(visits=visits + 1)
    assert (
        score(response=PastResponse.NOT_BOOKED)
        < score(response=PastResponse.NEVER)
        < score(response=PastResponse.BOOKED)
    )


# --- ordering --------------------------------------------------------------------------------


def test_ordering_is_score_then_spend_then_patient_id():
    a, b, c, d = (uuid.UUID(int=i) for i in (1, 2, 3, 4))
    items = [(b, 80, 500), (a, 80, 500), (c, 80, 900), (d, 90, 1)]
    ordered = sorted(items, key=lambda i: ordering_key(i[1], i[2], i[0]))
    assert [i[0] for i in ordered] == [d, c, a, b]  # score 90 first, then spend 900, then id 1 before id 2


def test_ordering_is_stable_under_shuffle():
    rng = random.Random(3)
    items = [(uuid.uuid4(), rng.choice([40, 41, 42]), rng.choice([0, 100, 100, 5000])) for _ in range(300)]
    want = sorted(items, key=lambda i: ordering_key(i[1], i[2], i[0]))
    for seed in range(5):
        shuffled = list(items)
        random.Random(seed).shuffle(shuffled)
        assert sorted(shuffled, key=lambda i: ordering_key(i[1], i[2], i[0])) == want
