import random
import uuid
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction

import pytest
from builders import blank
from factories import NOW, TZ, Scene, at
from pydantic import ValidationError

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_reactivation.analysis.exclusions import assign_spend_percentiles
from clinic_reactivation.analysis.facts import load_facts
from clinic_reactivation.analysis.settings import DormantRule, ReactivationSettings
from clinic_reactivation.analysis.types import (
    Classification,
    classify,
    classify_all,
    days_since_last_visit,
    interval_for,
    is_at_risk,
    is_dormant,
    local_today,
)

S = ReactivationSettings()
TODAY = date(2026, 6, 1)  # NOW is 11:00 on this day in New York


def facts(days=130, *, visits=3, **kw):
    """A scored patient whose last visit was `days` clinic-local days before TODAY."""
    kw.setdefault("usual_service_visit_days", 1)
    return blank(visit_count=visits, last_visit_day=TODAY - timedelta(days=days), **kw)


def run(f, settings=S, now=NOW) -> Classification:
    return classify(f, settings, now, TZ)


def tweak(settings=S, **groups):
    """Settings with fields changed WITHOUT validation, as the tests need values the model would refuse."""
    return settings.model_copy(update=groups)


def type_rule(settings, key, **changes):
    rules = settings.types.model_copy(update={key: getattr(settings.types, key).model_copy(update=changes)})
    return settings.model_copy(update={"types": rules})


def dormant_rule(settings=S, **changes):
    return settings.model_copy(update={"dormant": settings.dormant.model_copy(update=changes)})


# --- time ------------------------------------------------------------------------------------


def test_days_are_clinic_local_calendar_days():
    last = date(2026, 3, 3)
    f = blank(visit_count=2, last_visit_day=last)
    assert days_since_last_visit(f, date(2026, 6, 1)) == 90
    # 02:00 UTC on 2 June is still 1 June in New York, so 90 days, not 91
    late = datetime(2026, 6, 2, 2, tzinfo=UTC)
    assert local_today(late, TZ) == date(2026, 6, 1)
    assert days_since_last_visit(f, local_today(late, TZ)) == 90
    assert local_today(late, "UTC") == date(2026, 6, 2)
    assert days_since_last_visit(blank(), TODAY) is None
    with pytest.raises(ValueError, match="timezone-aware"):
        local_today(datetime(2026, 6, 1, 15), TZ)


# --- interval --------------------------------------------------------------------------------


def test_interval_order_is_service_then_category_then_default():
    service = uuid.uuid4()
    rules = dict(
        rebooking_days_by_service={service: 60},
        rebooking_days_by_category={"Injectables": 90},
        default_rebooking_days=120,
    )
    s = dormant_rule(**rules)
    both = facts(usual_service_id=service, usual_service_category_norm="injectables")
    assert (interval_for(both, s).days, interval_for(both, s).source) == (60, "service")
    category = facts(usual_service_id=uuid.uuid4(), usual_service_category_norm="injectables")
    assert (interval_for(category, s).days, interval_for(category, s).source) == (90, "category")
    neither = facts(usual_service_id=uuid.uuid4(), usual_service_category_norm="laser")
    assert (interval_for(neither, s).days, interval_for(neither, s).source) == (120, "default")
    assert interval_for(facts(), s) == interval_for(neither, s).__class__(120, "default", 0)


def test_category_match_ignores_case_and_spacing():
    s = dormant_rule(rebooking_days_by_category={"  INJECTABLES ": 75})
    assert interval_for(facts(usual_service_category_norm="injectables"), s).days == 75


@pytest.mark.parametrize("bad", [0, -5, None, True])
def test_a_service_interval_that_is_zero_or_unusable_falls_back_and_is_counted(bad):
    service = uuid.uuid4()
    s = dormant_rule(rebooking_days_by_service={service: bad}, rebooking_days_by_category={"injectables": 90})
    got = interval_for(facts(usual_service_id=service, usual_service_category_norm="injectables"), s)
    assert (got.days, got.source, got.invalid_levels_skipped) == (90, "category", 1)
    plain = interval_for(facts(usual_service_id=service), s)
    assert (plain.days, plain.source, plain.invalid_levels_skipped) == (120, "default", 1)
    assert "invalid_rebooking_interval" in run(facts(usual_service_id=service), s).quality_flags


def test_a_missing_service_interval_falls_back_without_counting():
    s = dormant_rule(rebooking_days_by_service={uuid.uuid4(): 60})
    got = interval_for(facts(usual_service_id=uuid.uuid4()), s)
    assert (got.days, got.source, got.invalid_levels_skipped) == (120, "default", 0)
    assert "invalid_rebooking_interval" not in run(facts(usual_service_id=uuid.uuid4()), s).quality_flags


def test_a_bad_category_value_and_a_bad_default_never_give_an_interval_below_one():
    cat = dormant_rule(rebooking_days_by_category={"injectables": 0})
    got = interval_for(facts(usual_service_category_norm="injectables"), cat)
    assert (got.days, got.source, got.invalid_levels_skipped) == (120, "default", 1)
    broken = dormant_rule(default_rebooking_days=0)
    got = interval_for(facts(), broken)
    assert got.days >= 1 and got.invalid_levels_skipped == 1


def test_no_usual_service_uses_the_default_and_is_flagged():
    r = run(facts(usual_service_id=None))
    assert r.interval_days == 120 and r.interval_source == "default" and "missing_service_on_visits" in r.quality_flags
    assert "missing_service_on_visits" not in run(facts(usual_service_id=uuid.uuid4())).quality_flags


# --- dormant and at risk ---------------------------------------------------------------------


def test_days_exactly_at_the_interval_and_one_more():
    at_interval, one_more = run(facts(120)), run(facts(121))
    assert at_interval.status == "at_risk"  # the interval is not "over" it
    assert one_more.status == "dormant"
    assert is_at_risk(facts(120), S, NOW, TZ) and not is_dormant(facts(120), S, NOW, TZ)
    assert is_dormant(facts(121), S, NOW, TZ) and not is_at_risk(facts(121), S, NOW, TZ)


def test_the_general_rule_also_fires_on_the_minimum_days():
    short = dormant_rule(min_days_since_visit=60)  # shorter than the interval of 120
    assert run(facts(60), short).status != "dormant"
    assert run(facts(61), short).status == "dormant"


def test_at_risk_at_point_eight_and_point_seven_nine():
    s = dormant_rule(default_rebooking_days=100)
    assert run(facts(80), s).status == "at_risk"
    assert run(facts(79), s).status == "active"
    assert run(facts(100), s).status == "at_risk" and run(facts(101), s).status == "dormant"


def test_ratio_thresholds_are_exact_not_floating_point():
    # 0.7 * 10 is 7.000000000000001 in floats, which would wrongly say 7 days is not at risk
    s = dormant_rule(default_rebooking_days=10, at_risk_ratio_min=0.7)
    assert run(facts(7), s).status == "at_risk" and run(facts(6), s).status == "active"
    odd = type_rule(S, "overdue_maintenance", overdue_ratio_min=1.1)
    f = facts(110, usual_service_visit_days=3)
    g = dormant_rule(odd, default_rebooking_days=100)
    assert "overdue_maintenance" not in run(f, g).matched_types  # exactly 1.1, and the rule says "above"
    assert "overdue_maintenance" in run(facts(111, usual_service_visit_days=3), g).matched_types


def test_a_future_booking_is_never_dormant_or_at_risk():
    for days in (60, 100, 120, 121, 500, 2000):
        f = facts(days, has_future_booking=True, prepaid_balance_cents=5000, usual_service_visit_days=5)
        r = run(f)
        assert r.status == "active" and r.matched_types == () and r.primary_type is None
        assert not is_dormant(f, S, NOW, TZ) and not is_at_risk(f, S, NOW, TZ)
    own_rule = facts(100, visits=1, has_future_booking=True)  # one_and_done would otherwise match
    assert run(own_rule).status == "active"
    assert run(facts(100, visits=1)).status == "dormant"


def test_a_patient_with_no_visits_is_not_judged():
    r = run(blank(visit_count=0))
    assert r.status == "no_visits" and r.days_since_last_visit is None and r.matched_types == ()


# --- one_and_done and D11 --------------------------------------------------------------------


@pytest.mark.parametrize(("days", "matches"), [(89, False), (90, False), (91, True)])
def test_one_and_done_is_strictly_over_90_days(days, matches):
    r = run(facts(days, visits=1))
    assert ("one_and_done" in r.matched_types) is matches
    assert (r.status == "dormant") is matches


def test_a_one_visit_patient_at_100_days_is_dormant_through_the_types_own_rule():
    r = run(facts(100, visits=1))
    assert r.status == "dormant" and r.primary_type == "one_and_done"
    assert 100 <= S.dormant.min_days_since_visit and 100 <= r.interval_days  # the general rule does not hold
    assert any("Only one visit, 100 days ago" in line for line in r.reasons)
    assert run(facts(100, visits=2)).status == "at_risk"  # two visits: no such rule, just approaching the interval


# --- lapsed_high_value and overdue_maintenance (D2) ------------------------------------------


def test_ratio_exactly_two_is_lapsed_high_value_and_not_maintenance():
    top = dict(spend_percentile=Fraction(9, 10), usual_service_visit_days=4)
    exactly_two = run(facts(240, **top))
    # lapsed_regular also matches any repeat dormant patient (D13); the priority picks the primary type
    assert exactly_two.matched_types == ("lapsed_high_value", "lapsed_regular")
    assert exactly_two.primary_type == "lapsed_high_value"
    just_under = run(facts(239, **top))
    assert just_under.matched_types == ("overdue_maintenance", "lapsed_regular")
    just_over = run(facts(241, **top))
    assert just_over.matched_types == ("lapsed_high_value", "lapsed_regular")


def test_lapsed_high_value_needs_the_percentile_and_the_ratio():
    assert "lapsed_high_value" in run(facts(240, spend_percentile=Fraction(80, 100))).matched_types
    assert "lapsed_high_value" not in run(facts(240, spend_percentile=Fraction(79, 100))).matched_types
    assert "lapsed_high_value" not in run(facts(239, spend_percentile=Fraction(1))).matched_types


def test_lapsed_high_value_is_skipped_when_the_cohort_is_under_20():
    f = facts(300, spend_percentile=None)
    r = run(f)
    assert "lapsed_high_value" not in r.matched_types
    assert r.skipped_types == ("lapsed_high_value:cohort_too_small",)
    assert r.status == "dormant" and r.primary_type == "lapsed_regular"  # ratio 2.5 is above maintenance's range
    # end to end: 19 scored patients get no percentile, 20 do, with the cohort minimum from settings
    cohort = [facts(300, spend_cents=i * 100, patient_id=uuid.uuid4()) for i in range(19)]
    small = assign_spend_percentiles(cohort, cohort_min=S.limits.spend_cohort_minimum)
    assert all(run(x).skipped_types and "lapsed_high_value" not in run(x).matched_types for x in small)
    big = assign_spend_percentiles(
        cohort + [facts(300, spend_cents=1900, patient_id=uuid.uuid4())], cohort_min=S.limits.spend_cohort_minimum
    )
    top = max(big, key=lambda x: x.spend_cents)
    assert run(top).primary_type == "lapsed_high_value" and run(top).skipped_types == ()


def test_overdue_maintenance_needs_two_visits_of_the_usual_service_and_the_range():
    assert run(facts(150, usual_service_visit_days=2)).matched_types == ("overdue_maintenance", "lapsed_regular")
    assert run(facts(150, usual_service_visit_days=1)).matched_types == ("lapsed_regular",)
    assert run(facts(120, usual_service_visit_days=2)).status == "at_risk"  # not above the interval yet
    assert run(facts(121, usual_service_visit_days=2)).matched_types == ("overdue_maintenance", "lapsed_regular")


# --- consult_not_converted -------------------------------------------------------------------


def consult(days_ago, converted=False, **kw):
    return facts(30, latest_consult_day=TODAY - timedelta(days=days_ago), converted_within_window=converted, **kw)


def test_consult_on_day_60_does_not_match_and_on_day_61_does():
    assert "consult_not_converted" not in run(consult(60)).matched_types
    r = run(consult(61))
    assert r.matched_types == ("consult_not_converted",) and r.status == "dormant"
    assert any("61 days ago" in line for line in r.reasons)


def test_a_consult_inside_the_window_or_one_that_converted_does_not_match():
    assert run(consult(30)).matched_types == ()
    assert run(consult(100, converted=True)).matched_types == ()
    assert run(consult(100, converted=None)).matched_types == ()  # no consult on record
    assert run(facts(30)).matched_types == ()


def test_the_consult_window_comes_from_settings():
    s = type_rule(S, "consult_not_converted", conversion_window_days=30)
    assert "consult_not_converted" in run(consult(31), s).matched_types
    assert "consult_not_converted" not in run(consult(30), s).matched_types


# --- churned_member --------------------------------------------------------------------------


def member(status="cancelled", end=date(2026, 1, 31), last_visit=date(2026, 3, 1), **kw):
    return blank(
        visit_count=3,
        last_visit_day=last_visit,
        latest_membership_status=status,
        latest_membership_end=end,
        usual_service_visit_days=1,
        **kw,
    )


def test_a_churned_member_who_has_not_visited_since_the_membership_ended_is_matched():
    for status in ("cancelled", "lapsed", "expired"):
        r = run(member(status, last_visit=date(2026, 1, 15)))
        assert r.matched_types == ("churned_member", "lapsed_regular") and r.status == "dormant"
    on_the_day = run(member(last_visit=date(2026, 1, 31)))
    assert on_the_day.matched_types == ("churned_member", "lapsed_regular")  # a visit on the end date is not after it


def test_a_churned_member_who_visited_after_the_membership_ended_is_not_matched():
    r = run(member(end=date(2025, 12, 31), last_visit=date(2026, 1, 15)))  # back 15 days after it ended
    assert "churned_member" not in r.matched_types
    assert r.status == "dormant" and r.primary_type == "lapsed_regular"  # dormant by the general rule, a repeat patient


def test_a_member_with_an_active_membership_is_not_churned():
    assert run(member(has_active_membership=True, last_visit=date(2026, 1, 15))).matched_types == ("lapsed_regular",)
    assert run(member("active", last_visit=date(2026, 1, 15))).matched_types == ("lapsed_regular",)


def test_an_unknown_membership_status_is_not_churned_and_is_counted():
    r = run(member("paused", last_visit=date(2026, 1, 15), unknown_membership_status={"paused": 1}))
    assert "churned_member" not in r.matched_types
    assert "unknown_membership_status" in r.quality_flags
    assert "unknown_membership_status" not in run(member(last_visit=date(2026, 1, 15))).quality_flags


def test_without_an_end_date_a_churned_member_needs_the_general_rule():
    no_end = dict(end=None)
    dormant = run(member(last_visit=date(2026, 1, 15), **no_end))  # 137 days: over the 120 day interval
    assert dormant.matched_types == ("churned_member", "lapsed_regular")
    recent = run(member(last_visit=TODAY - timedelta(days=50), **no_end))
    assert recent.matched_types == () and recent.status == "active"  # cannot make a patient dormant alone
    with_end = run(member(end=date(2026, 5, 1), last_visit=TODAY - timedelta(days=50)))
    assert with_end.matched_types == ("churned_member",) and with_end.status == "dormant"  # its own entry rule


# --- unused_balance (Q2) ---------------------------------------------------------------------


def test_unused_balance_does_not_match_an_active_patient():
    r = run(facts(30, prepaid_balance_cents=9000))
    assert r.status == "active" and r.matched_types == ()
    assert run(facts(100, visits=2, prepaid_balance_cents=9000)).matched_types == ()


def test_unused_balance_matches_any_dormant_patient_but_never_creates_dormancy():
    one_and_done = run(facts(100, visits=1, prepaid_balance_cents=9000))
    assert one_and_done.matched_types == ("one_and_done", "unused_balance")  # dormant through a type's own rule
    assert one_and_done.primary_type == "one_and_done"
    alone = run(facts(130, prepaid_balance_cents=9000))
    assert alone.matched_types == ("lapsed_regular", "unused_balance") and alone.primary_type == "lapsed_regular"
    only = run(facts(130, prepaid_balance_cents=9000), type_rule(S, "lapsed_regular", enabled=False))
    assert only.matched_types == ("unused_balance",) and only.primary_type == "unused_balance"
    assert run(facts(130, prepaid_balance_cents=0)).matched_types == ("lapsed_regular",)


# --- primary type, unclassified, disabled ----------------------------------------------------


def test_primary_type_is_the_lowest_priority_number():
    f = facts(150, visits=1, usual_service_visit_days=2, prepaid_balance_cents=100)
    r = run(f)
    # defaults: overdue_maintenance is priority 4, one_and_done 5, unused_balance 6
    assert r.matched_types == ("overdue_maintenance", "one_and_done", "unused_balance")
    assert r.primary_type == "overdue_maintenance"
    flipped = type_rule(type_rule(S, "one_and_done", priority=2), "overdue_maintenance", priority=5)
    assert run(f, flipped).primary_type == "one_and_done"
    assert run(f, flipped).matched_types == ("one_and_done", "overdue_maintenance", "unused_balance")


def test_equal_priorities_fall_back_to_the_type_key():
    same = type_rule(type_rule(S, "one_and_done", priority=4), "overdue_maintenance", priority=4)
    r = run(facts(150, visits=1, usual_service_visit_days=2), same)
    assert r.matched_types == ("one_and_done", "overdue_maintenance")  # 'one_and_done' sorts first
    assert r.primary_type == "one_and_done"


def test_a_dormant_patient_matching_nothing_is_unclassified():
    r = run(facts(130), type_rule(S, "lapsed_regular", enabled=False))  # a repeat patient would be a lapsed regular
    assert r.status == "dormant" and r.primary_type is None and r.matched_types == ()
    assert any("matches none of the enabled patient types" in line for line in r.reasons)


def test_disabled_types_are_skipped():
    off = type_rule(S, "one_and_done", enabled=False)
    r = run(facts(100, visits=1), off)
    assert r.status == "at_risk" and r.matched_types == ()  # the type's own rule can no longer make them dormant
    still = run(facts(150, visits=1, usual_service_visit_days=2), off)
    assert still.matched_types == ("overdue_maintenance",)
    no_lapsed = type_rule(S, "lapsed_high_value", enabled=False)
    r = run(facts(300, spend_percentile=Fraction(1)), no_lapsed)
    assert r.matched_types == ("lapsed_regular",) and r.skipped_types == ()  # a disabled type is not "skipped"
    no_churn = run(member(last_visit=date(2026, 1, 15)), type_rule(S, "churned_member", enabled=False))
    assert no_churn.matched_types == ("lapsed_regular",)


def test_all_types_disabled():
    keys = (
        "lapsed_high_value",
        "churned_member",
        "consult_not_converted",
        "overdue_maintenance",
        "one_and_done",
        "lapsed_regular",
        "unused_balance",
    )
    s = S
    for key in keys:
        s = type_rule(s, key, enabled=False)
    assert run(facts(130, prepaid_balance_cents=500), s).status == "dormant"  # the general rule still applies
    assert run(facts(130, prepaid_balance_cents=500), s).matched_types == ()
    assert run(facts(100, visits=1), s).status == "at_risk"  # but no type can make anyone dormant on its own
    assert run(facts(100), s).status == "at_risk"


# --- settings that overlap -------------------------------------------------------------------


def test_a_settings_object_where_the_two_ratio_thresholds_overlap_is_rejected():
    config = ReactivationSettings().model_dump(mode="json")
    config["types"]["overdue_maintenance"]["overdue_ratio_max"] = 2.5
    with pytest.raises(ValidationError, match="overdue_ratio_max must be <= lapsed_high_value"):
        ReactivationSettings.model_validate(config)
    config["types"]["overdue_maintenance"]["overdue_ratio_max"] = 2.0
    assert ReactivationSettings.model_validate(config).types.overdue_maintenance.overdue_ratio_max == 2.0
    assert DormantRule().rebooking_days_by_service == {}


# --- order independence and invariants -------------------------------------------------------


def random_facts(rng: random.Random, n: int):
    out = []
    for _ in range(n):
        visits = rng.choice([1, 1, 2, 3, 6])
        out.append(
            blank(
                patient_id=uuid.UUID(int=rng.getrandbits(128), version=4),
                visit_count=visits,
                last_visit_day=TODAY - timedelta(days=rng.randint(0, 420)),
                usual_service_visit_days=rng.randint(0, visits),
                spend_percentile=rng.choice([None, Fraction(rng.randint(0, 100), 100)]),
                has_future_booking=rng.random() < 0.1,
                prepaid_balance_cents=rng.choice([0, 0, 4500]),
                latest_membership_status=rng.choice([None, "cancelled", "paused", "active", "expired"]),
                latest_membership_end=rng.choice([None, date(2026, 2, 1), date(2026, 5, 1)]),
                has_active_membership=rng.random() < 0.1,
                latest_consult_day=rng.choice([None, TODAY - timedelta(days=rng.randint(10, 150))]),
                converted_within_window=rng.choice([None, True, False]),
            )
        )
    return out


def test_shuffling_the_input_gives_identical_output():
    rng = random.Random(42)
    items = random_facts(rng, 400)
    want = classify_all(items, S, NOW, TZ)
    for seed in range(4):
        shuffled = list(items)
        random.Random(seed).shuffle(shuffled)
        assert classify_all(shuffled, S, NOW, TZ) == want
    assert [c.patient_id.int for c in want] == sorted(c.patient_id.int for c in want)


def test_results_always_satisfy_the_basic_invariants():
    for c in classify_all(random_facts(random.Random(9), 600), S, NOW, TZ):
        assert c.status in {"dormant", "at_risk", "active", "no_visits"}
        if c.primary_type is not None:
            assert c.status == "dormant" and c.primary_type == c.matched_types[0]
        if c.status != "dormant":
            assert c.matched_types == ()
        assert c.interval_days >= 1 and c.reasons
        assert list(c.matched_types) == sorted(set(c.matched_types), key=lambda k: (getattr(S.types, k).priority, k))


def test_a_classification_is_immutable():
    c = run(facts(130))
    with pytest.raises(AttributeError):
        c.status = "active"  # type: ignore[misc]


# --- from real facts -------------------------------------------------------------------------


async def test_consults_and_churn_from_real_facts():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    consult = sc.service("Consult", "Consult")
    botox = sc.service("Botox", "Injectables")

    second = sc.patient("second_consult")  # a second consult does not convert
    sc.appt(second, "completed", at(2026, 2, 21), consult)
    sc.appt(second, "completed", at(2026, 3, 23), consult)

    day60 = sc.patient("converted_day_60")
    sc.appt(day60, "completed", at(2026, 2, 10), consult)
    sc.appt(day60, "completed", at(2026, 4, 11), botox)
    day61 = sc.patient("converted_day_61")
    sc.appt(day61, "completed", at(2026, 2, 10), consult)
    sc.appt(day61, "completed", at(2026, 4, 12), botox)

    after_end = sc.patient("visited_after_end")
    sc.membership(after_end, "cancelled", ends=date(2026, 1, 31), fee=9900)
    sc.appt(after_end, "completed", at(2025, 12, 1), botox)
    sc.appt(after_end, "completed", at(2026, 3, 1), botox)
    before_end = sc.patient("not_back_since")
    sc.membership(before_end, "cancelled", ends=date(2026, 2, 28), fee=9900)
    sc.appt(before_end, "completed", at(2025, 12, 1), botox)
    sc.appt(before_end, "completed", at(2026, 2, 15), botox)
    on_end_day = sc.patient("visit_on_end_day")
    sc.membership(on_end_day, "cancelled", ends=date(2026, 2, 28), fee=9900)
    sc.appt(on_end_day, "completed", at(2025, 12, 1), botox)
    sc.appt(on_end_day, "completed", at(2026, 2, 28), botox)
    await sc.save()

    async with tenant_session(tenant) as s:
        loaded = await load_facts(s, NOW, TZ)
    got = {c.patient_id: c for c in classify_all(loaded, S, NOW, TZ)}

    assert got[second.id].matched_types == ("consult_not_converted",)  # the latest consult is 70 days old
    assert "consult_not_converted" not in got[day60.id].matched_types  # treated on day 60 of the window
    assert got[day61.id].matched_types == ("consult_not_converted",)  # day 61 is outside the window
    assert "churned_member" not in got[after_end.id].matched_types
    assert got[before_end.id].matched_types == ("churned_member",)
    assert got[on_end_day.id].matched_types == ("churned_member",)


async def test_classifications_feed_revenue_points_and_scoring_unchanged():
    from factories import build_messy_tenant

    from clinic_reactivation.analysis.points import PreviousRun, analysis_points, data_available
    from clinic_reactivation.analysis.revenue import (
        RevenueContext,
        RevenueInput,
        practice_median_first_treatment_ticket,
        summarise_revenue,
    )
    from clinic_reactivation.analysis.scoring import PastResponse, RatioInputs, likelihood_score

    messy = await build_messy_tenant()
    async with tenant_session(messy.tenant) as s:
        loaded = await load_facts(s, NOW, TZ, cohort_min=S.limits.spend_cohort_minimum)
    by_id = {f.patient_id: f for f in loaded}
    classes = classify_all(loaded, S, NOW, TZ)
    assert {c.status for c in classes} >= {"dormant", "at_risk", "active", "no_visits"}

    inputs = [RevenueInput(by_id[c.patient_id], c.status, c.primary_type, c.matched_types) for c in classes]
    context = RevenueContext(practice_median_first_treatment_ticket(loaded))
    summary = summarise_revenue(inputs, context, S)
    assert summary.new_low_cents <= summary.new_high_cents and summary.retention_cents >= 0

    previous = PreviousRun(frozenset(c.patient_id for c in classes if c.status == "dormant"))
    for c in classes:
        if c.status not in ("dormant", "at_risk"):
            continue
        f = by_id[c.patient_id]
        points = analysis_points(f, c.status, c.primary_type, S, NOW, TZ, previous)
        assert "best_offer" in points and "change_since_last" in points
        score = likelihood_score(f, RatioInputs(c.days_since_last_visit, c.interval_days), PastResponse.NEVER)
        assert type(score) is int and 0 <= score <= 100
    assert data_available(loaded)["staff"] is True
