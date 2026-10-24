"""The optional dollar cutoff for top spenders: it adds a rule beside the percentile and changes nothing when empty."""

import uuid
from dataclasses import replace
from datetime import date, timedelta
from fractions import Fraction

from builders import blank
from factories import NOW, TZ, Scene, at

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_reactivation.analysis.engine import analyse
from clinic_reactivation.analysis.facts import load_facts
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.analysis.types import classify, classify_all

TODAY = date(2026, 6, 1)  # NOW is 11:00 on this day in New York
CUTOFF = 50_000  # $500.00
SKIPPED = ("lapsed_high_value:cohort_too_small",)
PERCENTILE_TEXT = (
    "In the top 20% of patients by spend and 250 days since the last visit, 2.1 times the usual 120 day interval."
)
DOLLAR_TEXT = (
    "Spent more than $500.00 in total and 250 days since the last visit, 2.1 times the usual 120 day interval."
)


def settings(cutoff=None) -> ReactivationSettings:
    config = ReactivationSettings().model_dump(mode="json")
    config["types"]["lapsed_high_value"]["spend_cents_min"] = cutoff
    return ReactivationSettings.model_validate(config)


def patient(*, spend, percentile, days=250):
    """Dormant, 2.1 times the usual interval overdue, with the given lifetime spend and percentile."""
    return blank(
        visit_count=3,
        last_visit_day=TODAY - timedelta(days=days),
        usual_service_visit_days=1,
        spend_cents=spend,
        spend_percentile=percentile,
    )


def run(f, s):
    return classify(f, s, NOW, TZ)


def reason(c):
    return dict(zip(c.matched_types, c.type_reasons, strict=True)).get("lapsed_high_value")


# --- a cohort too small for a percentile ------------------------------------------------------


def test_cutoff_set_and_cohort_too_small_the_dollar_rule_still_applies():
    c = run(patient(spend=CUTOFF + 1, percentile=None), settings(CUTOFF))
    assert "lapsed_high_value" in c.matched_types
    assert reason(c) == DOLLAR_TEXT
    assert c.skipped_types == SKIPPED  # the percentile rule was skipped and the result says so


def test_cutoff_set_but_not_exceeded_with_a_small_cohort_matches_nothing():
    c = run(patient(spend=CUTOFF - 1, percentile=None), settings(CUTOFF))
    assert "lapsed_high_value" not in c.matched_types and c.skipped_types == SKIPPED


def test_cutoff_empty_and_cohort_too_small_behaves_as_before():
    c = run(patient(spend=10_000_000, percentile=None), settings(None))
    assert "lapsed_high_value" not in c.matched_types
    assert c.skipped_types == SKIPPED
    assert c.status == "dormant"  # still dormant by the general rule


# --- the boundary ----------------------------------------------------------------------------


def test_the_cutoff_is_strictly_greater_than():
    s = settings(CUTOFF)
    assert "lapsed_high_value" not in run(patient(spend=CUTOFF, percentile=None), s).matched_types
    assert "lapsed_high_value" in run(patient(spend=CUTOFF + 1, percentile=None), s).matched_types


def test_the_dollar_rule_still_needs_the_patient_to_be_overdue():
    f = patient(spend=CUTOFF + 1, percentile=None, days=200)  # 1.67 times the interval, below the 2.0 needed
    assert "lapsed_high_value" not in run(f, settings(CUTOFF)).matched_types


# --- the two reasons --------------------------------------------------------------------------


def test_a_percentile_match_keeps_the_existing_reason_text():
    f = patient(spend=1000, percentile=Fraction(9, 10))
    for s in (settings(None), settings(CUTOFF)):  # a cutoff that does not apply changes nothing
        assert reason(run(f, s)) == PERCENTILE_TEXT


def test_a_dollar_only_match_gives_the_dollar_reason():
    f = patient(spend=CUTOFF + 1, percentile=Fraction(1, 10))  # below the top 20%, above the cutoff
    assert reason(run(f, settings(CUTOFF))) == DOLLAR_TEXT
    assert "lapsed_high_value" not in run(f, settings(None)).matched_types


def test_when_both_rules_apply_the_percentile_reason_is_given():
    f = patient(spend=CUTOFF + 1, percentile=Fraction(95, 100))
    assert reason(run(f, settings(CUTOFF))) == PERCENTILE_TEXT


# --- a refund, from real transactions ---------------------------------------------------------


async def test_a_refund_that_drops_spend_below_the_cutoff_removes_the_match():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    botox = sc.service("Botox", "Injectables")
    kept, refunded = sc.patient("kept"), sc.patient("refunded")
    for p in (kept, refunded):
        sc.appt(p, "completed", at(2025, 8, 1), botox)
        sc.txn(p, 60_000, when=at(2025, 8, 1))
    sc.txn(refunded, -20_000, when=at(2025, 8, 2))  # net 40,000: below the 50,000 cutoff
    await sc.save()

    s = settings(CUTOFF)
    async with tenant_session(tenant) as session:
        loaded = await load_facts(session, NOW, TZ, cohort_min=s.limits.spend_cohort_minimum)
    spend = {f.patient_id: f.spend_cents for f in loaded}
    assert (spend[kept.id], spend[refunded.id]) == (60_000, 40_000)
    got = {c.patient_id: c for c in classify_all(loaded, s, NOW, TZ)}
    assert "lapsed_high_value" in got[kept.id].matched_types
    assert "lapsed_high_value" not in got[refunded.id].matched_types


# --- the engine reports the type as available -------------------------------------------------


def test_the_engine_stops_calling_the_group_unavailable_when_a_cutoff_is_set():
    pool = [replace(patient(spend=60_000 + i, percentile=None), patient_id=uuid.UUID(int=i + 1)) for i in range(5)]
    without = analyse(pool, settings(None), {}, {}, None, NOW, TZ)
    with_cutoff = analyse(pool, settings(CUTOFF), {}, {}, None, NOW, TZ)
    assert without.summary["types_data_available"]["lapsed_high_value"] is False
    assert with_cutoff.summary["types_data_available"]["lapsed_high_value"] is True
    assert [t.patient_count for t in with_cutoff.types if t.type_key == "lapsed_high_value"] == [5]
