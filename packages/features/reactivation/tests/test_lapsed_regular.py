"""lapsed_regular (spec 4.7, D13): repeat patients far past their return time who no other type claimed."""

import random
import uuid
from datetime import date, datetime, timedelta
from fractions import Fraction

import pytest
from builders import blank
from factories import NOW, TZ, Scene, at

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_reactivation.analysis.engine import analyse
from clinic_reactivation.analysis.facts import load_facts
from clinic_reactivation.analysis.revenue import RevenueContext, RevenueInput, revenue_basis, summarise_revenue
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.analysis.types import classify, classify_all
from clinic_reactivation.labels import TYPE_INFO

S = ReactivationSettings()  # interval 120 days, general dormant rule 180 days
TODAY = date(2026, 6, 1)  # NOW is 11:00 on this day in New York
CTX = RevenueContext(median_first_treatment_ticket_cents=30000)


def facts(days, *, visits=3, **kw):
    """A scored patient whose last visit was `days` clinic-local days before TODAY."""
    kw.setdefault("usual_service_visit_days", 1)  # not a repeat of one service: overdue_maintenance stays out
    return blank(visit_count=visits, last_visit_day=TODAY - timedelta(days=days), **kw)


def run(f, settings=S):
    return classify(f, settings, NOW, TZ)


def type_rule(settings, key, **changes):
    rules = settings.types.model_copy(update={key: getattr(settings.types, key).model_copy(update=changes)})
    return settings.model_copy(update={"types": rules})


# --- the entry rule --------------------------------------------------------------------------


def test_a_repeat_patient_far_past_the_interval_who_is_not_a_top_spender_is_a_lapsed_regular():
    r = run(facts(300, spend_percentile=Fraction(1, 2)))  # 2.5 times the interval, above maintenance's range
    assert r.status == "dormant" and r.primary_type == "lapsed_regular" and r.matched_types == ("lapsed_regular",)
    assert any("Repeat patient with 3 visits" in line for line in r.reasons)


def test_a_top_spender_at_twice_the_interval_or_more_stays_lapsed_high_value():
    for days in (240, 241, 400):
        r = run(facts(days, spend_percentile=Fraction(9, 10)))
        assert r.primary_type == "lapsed_high_value", days
        assert r.matched_types == ("lapsed_high_value", "lapsed_regular")  # still matched, the priority picks


def test_one_to_two_times_the_interval_with_two_visits_and_a_non_repeated_service_is_a_lapsed_regular():
    r = run(facts(150, visits=2, spend_percentile=Fraction(1, 2)))
    assert r.primary_type == "lapsed_regular" and r.matched_types == ("lapsed_regular",)
    # the same patient who repeats their usual service goes to overdue_maintenance (priority 4 beats 5)
    repeat = run(facts(150, visits=2, usual_service_visit_days=2))
    assert repeat.primary_type == "overdue_maintenance"
    assert repeat.matched_types == ("overdue_maintenance", "lapsed_regular")


def test_two_visits_is_the_minimum_and_a_single_visit_stays_one_and_done():
    one = run(facts(150, visits=1))
    assert one.primary_type == "one_and_done" and one.matched_types == ("one_and_done",)
    assert run(facts(150, visits=2)).primary_type == "lapsed_regular"


def test_it_never_creates_dormancy():
    assert run(facts(120, visits=5)).status == "at_risk"  # at the interval, not past it
    assert run(facts(100, visits=5)).matched_types == ()
    assert run(facts(60, visits=5)).status == "active"
    just_past = run(facts(121, visits=2))  # the general rule: days > interval
    assert just_past.status == "dormant" and just_past.matched_types == ("lapsed_regular",)
    # the general rule is days > interval or days > min_days_since_visit (180); lapsed_regular adds no third route
    long_interval = S.model_copy(update={"dormant": S.dormant.model_copy(update={"default_rebooking_days": 200})})
    assert run(facts(170, visits=5), long_interval).matched_types == ()  # past neither 200 nor 180
    assert run(facts(181, visits=5), long_interval).matched_types == ("lapsed_regular",)  # past the 180 day limit


def test_a_future_booking_overrides_it():
    assert run(facts(300, has_future_booking=True)).matched_types == ()


def test_a_patient_with_a_balance_has_lapsed_regular_as_primary_and_still_counts_in_retention():
    f = facts(150, prepaid_balance_cents=9000)
    r = run(f)
    assert r.primary_type == "lapsed_regular" and r.matched_types == ("lapsed_regular", "unused_balance")
    summary = summarise_revenue([RevenueInput(f, r.status, r.primary_type, r.matched_types)], CTX, S)
    assert summary.retention_cents == 9000  # the balance is retention value whatever the primary type
    rows = {row.type_key: row for row in summary.rows}
    assert rows["lapsed_regular"].patient_count == 1 and rows["unused_balance"].patient_count == 0


# --- settings --------------------------------------------------------------------------------


def test_defaults_are_enabled_priority_five_and_no_thresholds():
    rule = S.types.lapsed_regular
    assert (rule.enabled, rule.priority) == (True, 5)
    assert set(type(rule).model_fields) == {"enabled", "priority"}


def test_saved_settings_without_the_new_type_load_with_its_defaults():
    saved = S.model_dump(mode="json")
    del saved["types"]["lapsed_regular"]
    loaded = ReactivationSettings.model_validate(saved)
    assert loaded == S and loaded.types.lapsed_regular.enabled and loaded.types.lapsed_regular.priority == 5
    # a saved object that customised other types keeps them
    saved["types"]["one_and_done"]["priority"] = 5  # already the default; a tie with the new type is accepted
    saved["types"]["churned_member"]["enabled"] = False
    custom = ReactivationSettings.model_validate(saved)
    assert custom.types.churned_member.enabled is False and custom.types.lapsed_regular.priority == 5


def test_switching_the_type_off_leaves_those_patients_unclassified():
    off = type_rule(S, "lapsed_regular", enabled=False)
    r = run(facts(300, spend_percentile=Fraction(1, 2)), off)
    assert r.status == "dormant" and r.primary_type is None and r.matched_types == ()
    assert run(facts(150, visits=2), off).primary_type is None


# --- ties and determinism --------------------------------------------------------------------


def _population(n=60):
    rng = random.Random(7)
    return [
        blank(
            patient_id=uuid.UUID(int=i + 1),
            visit_count=rng.choice([1, 2, 3, 6]),
            last_visit_day=TODAY - timedelta(days=rng.choice([30, 100, 125, 150, 200, 260, 400])),
            usual_service_visit_days=rng.choice([1, 2]),
            prepaid_balance_cents=rng.choice([0, 0, 5000]),
            spend_cents=1000 * (i + 1),
            average_ticket_cents=500 * (i + 1),
        )
        for i in range(n)
    ]


def test_a_tie_between_two_enabled_types_resolves_by_type_key_every_time():
    tied = type_rule(type_rule(S, "overdue_maintenance", priority=5), "lapsed_regular", priority=5)
    f = facts(150, visits=3, usual_service_visit_days=2)  # matches both
    results = {run(f, tied).matched_types for _ in range(5)}
    assert results == {("lapsed_regular", "overdue_maintenance")}  # 'lapsed_regular' sorts first
    assert run(f, tied).primary_type == "lapsed_regular"
    # the default tie with one_and_done never matters: one needs exactly 1 visit, the other at least 2
    default_tie = [S.types.lapsed_regular.priority, S.types.one_and_done.priority]
    assert default_tie[0] == default_tie[1]
    for visits in (1, 2, 3):
        assert len(run(facts(150, visits=visits)).matched_types) == 1


def test_shuffling_the_input_gives_identical_output():
    tied = type_rule(type_rule(S, "overdue_maintenance", priority=5), "lapsed_regular", priority=5)
    population = _population()
    for settings in (S, tied):
        expected = classify_all(population, settings, NOW, TZ)
        for seed in range(5):
            shuffled = population[:]
            random.Random(seed).shuffle(shuffled)
            assert classify_all(shuffled, settings, NOW, TZ) == expected


def test_the_whole_engine_output_is_identical_under_shuffled_input():
    tied = type_rule(type_rule(S, "overdue_maintenance", priority=5), "lapsed_regular", priority=5)
    population = [
        p.__class__(**{**{f: getattr(p, f) for f in p.__dataclass_fields__}, "visit_days": (p.last_visit_day,),
                       "visit_starts": (datetime(2026, 1, 5, 15, tzinfo=NOW.tzinfo),),
                       "first_visit_day": p.last_visit_day})
        for p in _population()
    ]  # fmt: skip
    for settings in (S, tied):
        expected = analyse(population, settings, {}, {}, None, NOW, TZ).to_dict()
        for seed in range(3):
            shuffled = population[:]
            random.Random(seed).shuffle(shuffled)
            assert analyse(shuffled, settings, {}, {}, None, NOW, TZ).to_dict() == expected


# --- revenue and labels ----------------------------------------------------------------------


def test_the_revenue_basis_is_the_patients_average_ticket_and_the_kind_is_new():
    basis = revenue_basis(
        "lapsed_regular", blank(average_ticket_cents=25000, usual_service_ticket_total_cents=99999), CTX, S
    )
    assert (basis.cents, basis.kind, basis.flags) == (25000, "new", ())  # not the usual-service ticket
    nothing = revenue_basis("lapsed_regular", blank(average_ticket_cents=None), CTX, S)
    assert (nothing.cents, nothing.flags) == (0, ("no_spend_recorded",))


def test_label_and_description():
    info = TYPE_INFO["lapsed_regular"]
    assert info.label == "Lapsed regulars"
    assert info.description == "Repeat patients who are past their usual return time"
    assert info.kind == "new"


@pytest.mark.parametrize("key", ["lapsed_regular"])
def test_the_type_is_registered_everywhere_a_type_is_defined(key):
    from clinic_reactivation.analysis.revenue import TYPE_KINDS
    from clinic_reactivation.analysis.types import TYPE_KEYS

    assert key in TYPE_KEYS and key in TYPE_KINDS and key in TYPE_INFO and hasattr(S.types, key)
    assert set(TYPE_KEYS) == set(TYPE_KINDS) == set(type(S.types).model_fields) == set(TYPE_INFO) - {"unclassified"}


# --- from real facts -------------------------------------------------------------------------


async def test_visits_are_distinct_days_when_read_from_the_database():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    botox = sc.service("Botox", "Injectables")
    facial = sc.service("Facial", "Facials")

    same_day = sc.patient("three_appointments_one_day")  # one sitting is one visit (D1), so not a regular
    for service in (botox, facial, botox):
        sc.appt(same_day, "completed", at(2025, 11, 3), service)
    two_days = sc.patient("two_visit_days")
    sc.appt(two_days, "completed", at(2025, 9, 3), botox)
    sc.appt(two_days, "completed", at(2025, 11, 3), facial)
    recent = sc.patient("two_visit_days_but_recent")  # not dormant, so not a regular
    sc.appt(recent, "completed", at(2026, 2, 3), botox)
    sc.appt(recent, "completed", at(2026, 5, 3), facial)
    await sc.save()

    async with tenant_session(tenant) as s:
        loaded = await load_facts(s, NOW, TZ)
    got = {c.patient_id: c for c in classify_all(loaded, S, NOW, TZ)}

    assert got[same_day.id].matched_types == ("one_and_done",)
    assert got[two_days.id].matched_types == ("lapsed_regular",) and got[two_days.id].primary_type == "lapsed_regular"
    assert got[recent.id].status == "active" and got[recent.id].matched_types == ()
