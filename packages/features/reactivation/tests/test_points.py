import random
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from builders import blank
from factories import NOW, TZ, Scene, at

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_reactivation.analysis.facts import ReachabilityIngredients, load_facts
from clinic_reactivation.analysis.points import (
    PreviousRun,
    analysis_points,
    best_offer,
    best_time,
    change_counts,
    change_since_last,
    data_available,
    provider_continuity,
    reachable,
    revenue_at_risk,
    seasonality,
)
from clinic_reactivation.analysis.settings import ReactivationSettings

S = ReactivationSettings()
NY = "America/New_York"


def utc(y, m, d, h=12, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=UTC)


def visits(*moments: datetime):
    """Facts with these visit starts (oldest first) and the matching local days in New York."""
    from zoneinfo import ZoneInfo

    days = tuple(m.astimezone(ZoneInfo(NY)).date() for m in moments)
    return blank(visit_starts=tuple(moments), visit_days=days, visit_count=len(moments))


# --- best_offer ------------------------------------------------------------------------------


def test_best_offer_is_the_usual_service_or_the_consulted_one():
    usual, consulted = uuid.uuid4(), uuid.uuid4()
    f = blank(usual_service_id=usual, latest_consult_service_id=consulted)
    assert best_offer(f, "one_and_done") == {"service_id": usual, "source": "usual_service"}
    assert best_offer(f, "consult_not_converted") == {"service_id": consulted, "source": "consulted_service"}
    assert best_offer(f, None)["service_id"] == usual
    none = best_offer(blank(), "overdue_maintenance")
    assert none == {"service_id": None, "source": None, "reason": "no_service_on_record"}
    assert best_offer(blank(usual_service_id=usual), "consult_not_converted")["service_id"] is None


# --- best_time -------------------------------------------------------------------------------


def test_best_time_needs_three_visits():
    two = best_time(visits(utc(2026, 3, 2, 15), utc(2026, 3, 9, 15)), NY)
    assert two == {"weekday": None, "band": None, "reason": "fewer_than_3_visits"}
    three = best_time(visits(utc(2026, 3, 2, 15), utc(2026, 3, 9, 15), utc(2026, 3, 16, 15)), NY)
    assert three["weekday"] == 0 and three["visits_used"] == 3  # all Mondays
    assert best_time(blank(), NY)["reason"] == "fewer_than_3_visits"


def test_best_time_uses_the_clinic_timezone_not_utc():
    # 02:00 UTC on a Tuesday is 21:00 on Monday in New York (EST)
    f = visits(utc(2026, 2, 3, 2), utc(2026, 2, 10, 2), utc(2026, 2, 17, 2))
    assert (best_time(f, NY)["weekday"], best_time(f, NY)["band"]) == (0, 7)
    assert (best_time(f, "UTC")["weekday"], best_time(f, "UTC")["band"]) == (1, 0)


def test_best_time_follows_a_dst_boundary():
    # the same 07:00 UTC is 02:00 before the change (band 0) and 03:00 after it (band 1); two of three are after
    f = visits(utc(2026, 3, 7, 7), utc(2026, 3, 9, 7), utc(2026, 3, 10, 7))
    assert best_time(f, NY)["band"] == 1
    assert best_time(f, "Etc/GMT+5")["band"] == 0  # a fixed UTC-5 zone would misplace them all in band 0


def test_best_time_breaks_ties_by_the_most_recent_visit():
    # Mon, Mon, Tue, Tue: two each, and the latest visit is a Tuesday
    f = visits(utc(2026, 3, 2, 15), utc(2026, 3, 9, 15), utc(2026, 3, 10, 15), utc(2026, 3, 17, 15))
    assert best_time(f, NY)["weekday"] == 1
    # same days, but the most recent is a Monday
    g = visits(utc(2026, 3, 3, 15), utc(2026, 3, 10, 15), utc(2026, 3, 16, 15), utc(2026, 3, 23, 15))
    assert best_time(g, NY)["weekday"] == 0
    # the band tie works the same way: 09:00, 09:00, 14:00, 14:00 -> the latest band wins
    h = visits(utc(2026, 6, 1, 13), utc(2026, 6, 2, 13), utc(2026, 6, 3, 18), utc(2026, 6, 4, 18))
    assert best_time(h, NY)["band"] == 4  # 14:00 EDT is hour 14, band 4


def test_weekday_and_band_are_independent_modes():
    # Mon 09:00, Mon 10:00, Wed 15:00 -> weekday Monday (2 of 3); band 3 for 09 and 10 (2 of 3)
    f = visits(utc(2026, 6, 1, 13), utc(2026, 6, 8, 14), utc(2026, 6, 10, 19))
    r = best_time(f, NY)
    assert (r["weekday"], r["band"]) == (0, 3)


@pytest.mark.parametrize(("hour", "band"), [(0, 0), (2, 0), (3, 1), (5, 1), (6, 2), (23, 7)])
def test_three_hour_band_edges(hour, band):
    f = visits(*(utc(2026, 6, day, hour) for day in (1, 2, 3)))
    assert best_time(f, "UTC")["band"] == band


# --- reachable and provider continuity -------------------------------------------------------


def test_reachable_uses_the_pinned_pure_function():
    open_to_both = blank(ingredients=ReachabilityIngredients(True, None, True, True, True))
    assert reachable(open_to_both) == {"sms": True, "email": True, "either": True}
    no_sms_consent = blank(ingredients=ReachabilityIngredients(None, None, True, False, True))
    assert reachable(no_sms_consent) == {"sms": False, "email": False, "either": False}  # flagged, not hidden
    revoked_but_email = blank(ingredients=ReachabilityIngredients(False, None, True, True, True))
    assert reachable(revoked_but_email) == {"sms": False, "email": True, "either": True}


def test_provider_continuity_states():
    provider = uuid.uuid4()
    assert provider_continuity(blank(usual_provider_id=provider, provider_staff_active=True)) == {"status": "active"}
    assert provider_continuity(blank(usual_provider_id=provider, provider_staff_active=False)) == {"status": "inactive"}
    assert provider_continuity(blank(usual_provider_id=None)) == {"status": "unknown"}  # provider missing
    assert provider_continuity(blank(usual_provider_id=provider, provider_staff_active=None)) == {"status": "unknown"}


# --- seasonality -----------------------------------------------------------------------------


def season(visit_days, today, window=45):
    f = blank(visit_days=tuple(visit_days))
    return seasonality(f, datetime.combine(today, datetime.min.time(), tzinfo=UTC) + timedelta(hours=15), NY, window)


JULY = [date(2024, 7, 10), date(2025, 7, 12)]


def test_seasonality_needs_two_distinct_years():
    assert season([date(2024, 7, 10)], date(2026, 4, 1)) == {"applies": False, "reason": "fewer_than_2_years"}
    two_visits_one_year = [date(2025, 7, 10), date(2025, 7, 20)]
    assert season(two_visits_one_year, date(2026, 4, 1))["reason"] == "fewer_than_2_years"
    assert season(JULY, date(2026, 4, 1))["applies"] is True


def test_seasonality_window_is_one_month_either_side():
    r = season(JULY, date(2026, 4, 1))
    # July visits fit centre months 6, 7 and 8; all see two years, so the earliest window (May to July) wins
    assert (r["month"], r["window_start"], r["window_end"], r["years"]) == (6, "2026-05-01", "2026-07-31", 2)


def test_seasonality_respects_the_45_day_window_on_both_edges():
    # the window starts on 1 May: 45 days earlier is 16 March
    assert season(JULY, date(2026, 3, 17))["applies"] is True  # starts in 45 days
    assert season(JULY, date(2026, 3, 16))["applies"] is False  # 46 days
    assert season(JULY, date(2026, 3, 16))["reason"] == "window_not_near"
    assert season(JULY, date(2026, 3, 16), window=46)["applies"] is True  # the window comes from settings
    assert (
        season(JULY, date(2026, 3, 27), window=35)["applies"] is True
        and season(JULY, date(2026, 3, 26), window=35)["applies"] is False
    )


def test_seasonality_includes_a_window_already_under_way():
    inside = season(JULY, date(2026, 6, 15))
    assert inside["applies"] is True and inside["window_start"] == "2026-05-01"
    late = season(JULY, date(2026, 8, 15))  # the May window has ended; June to August is under way
    assert late["applies"] is True and late["month"] == 7
    over = season(JULY, date(2026, 10, 15))
    assert over == {"applies": False, "reason": "window_not_near"}  # all three have ended, next year is far


def test_seasonality_wraps_december_to_january():
    january = [date(2024, 1, 5), date(2025, 1, 10)]
    r = season(january, date(2026, 11, 25))
    # the December centre month's window runs Nov to Jan, across the new year
    assert (r["month"], r["window_start"], r["window_end"]) == (12, "2026-11-01", "2027-01-31")
    decembers = [date(2024, 12, 28), date(2025, 12, 30)]
    assert season(decembers, date(2026, 11, 25))["applies"] is True


def test_one_winter_across_december_and_january_is_one_season_year():
    one_holiday = [date(2024, 12, 28), date(2025, 1, 5)]
    assert season(one_holiday, date(2026, 11, 25)) == {"applies": False, "reason": "fewer_than_2_years"}
    two_holidays = [date(2023, 12, 28), date(2024, 1, 5), date(2024, 12, 29), date(2025, 1, 3)]
    assert season(two_holidays, date(2026, 11, 25))["applies"] is True


# --- change since last run -------------------------------------------------------------------


def test_change_since_last_per_patient():
    a, b = uuid.uuid4(), uuid.uuid4()
    previous = PreviousRun(frozenset({a}))
    assert change_since_last(a, "dormant", None) == "first_run" == change_since_last(b, "at_risk", None)
    assert change_since_last(a, "dormant", previous) == "unchanged"
    assert change_since_last(b, "dormant", previous) == "new"
    assert change_since_last(a, "at_risk", previous) == "returned_since_last"
    assert change_since_last(b, "at_risk", previous) == "new"


def test_change_counts_count_only_scored_patients_as_returned():
    stays, comes_back_active, comes_back_at_risk, now_excluded, errored, new_dormant, new_at_risk = (
        uuid.uuid4() for _ in range(7)
    )
    previous = PreviousRun(frozenset({stays, comes_back_active, comes_back_at_risk, now_excluded, errored}))
    statuses = {
        stays: "dormant",
        comes_back_active: "active",
        comes_back_at_risk: "at_risk",
        new_dormant: "dormant",
        new_at_risk: "at_risk",
        # now_excluded (say, do-not-contact) and errored are not scored, so they are absent
    }
    counts = change_counts(previous, statuses)
    assert (counts.first_run, counts.new, counts.unchanged, counts.returned_since_last) == (False, 1, 1, 2)


def test_change_counts_without_a_previous_run_is_a_first_run():
    counts = change_counts(None, {uuid.uuid4(): "dormant"})
    assert (counts.first_run, counts.new, counts.unchanged, counts.returned_since_last) == (True, 0, 0, 0)
    assert change_counts(PreviousRun(frozenset()), {}).first_run is False


# --- revenue at risk -------------------------------------------------------------------------


def test_revenue_at_risk_applies_only_to_at_risk_patients():
    f = blank(average_ticket_cents=25000)
    assert revenue_at_risk(f, "at_risk") == {"cents": 25000}
    assert revenue_at_risk(f, "dormant") is None and revenue_at_risk(f, "active") is None
    assert revenue_at_risk(blank(average_ticket_cents=None), "at_risk") == {"cents": 0}


# --- the aggregate ---------------------------------------------------------------------------


def with_points(**switches) -> ReactivationSettings:
    return S.model_copy(update={"points": S.points.model_copy(update=switches)})


def points_for(settings, status="at_risk", primary=None, previous=None):
    facts = blank(visit_starts=(utc(2026, 3, 2, 15),) * 3, average_ticket_cents=900)
    return analysis_points(facts, status, primary, settings, NOW, NY, previous)


ALL = {"best_offer", "best_time", "reachable", "provider_continuity", "change_since_last", "revenue_at_risk"}


def test_defaults_give_every_point_except_seasonality():
    assert set(points_for(S)) == ALL  # seasonality is off by default
    assert set(points_for(with_points(seasonality=True))) == ALL | {"seasonality"}


@pytest.mark.parametrize("name", sorted(ALL | {"seasonality"}))
def test_a_disabled_point_is_absent_not_null(name):
    out = points_for(with_points(**{"seasonality": True, name: False}))
    assert name not in out
    assert all(value is not None for value in out.values())
    assert len(out) == len(ALL | {"seasonality"}) - 1


def test_all_points_off_gives_nothing():
    off = {n: False for n in ALL | {"seasonality"}}
    assert points_for(with_points(**off)) == {}


def test_revenue_at_risk_is_left_out_for_patients_who_are_not_at_risk():
    assert "revenue_at_risk" not in points_for(S, status="dormant")
    assert points_for(S, status="at_risk")["revenue_at_risk"] == {"cents": 900}


def test_the_change_point_carries_the_first_run_marker():
    assert points_for(S)["change_since_last"] == {"change": "first_run"}


def test_the_seasonality_window_comes_from_settings():
    f = blank(visit_days=tuple(JULY))
    near = S.model_copy(update={"points": S.points.model_copy(update={"seasonality": True})})
    narrow = near.model_copy(update={"limits": near.limits.model_copy(update={"seasonality_window_days": 10})})
    when = datetime(2026, 4, 1, 15, tzinfo=UTC)
    assert analysis_points(f, "dormant", None, near, when, NY, None)["seasonality"]["applies"] is True
    assert analysis_points(f, "dormant", None, narrow, when, NY, None)["seasonality"]["applies"] is False


# --- data available --------------------------------------------------------------------------


def test_data_available_reports_an_empty_source_as_unavailable():
    nothing = data_available([blank(), blank()])
    assert nothing == {"staff": False, "memberships": False, "consents": False, "services": False}
    some = data_available(
        [
            blank(),
            blank(
                provider_staff_active=False,
                membership_rows=1,
                usual_service_id=uuid.uuid4(),
                ingredients=ReachabilityIngredients(None, False, True, True, True),
            ),
        ]
    )
    assert some == {"staff": True, "memberships": True, "consents": True, "services": True}
    assert data_available([]) == {"staff": False, "memberships": False, "consents": False, "services": False}


def test_shuffling_does_not_change_the_points():
    rng = random.Random(5)
    items = [blank(patient_id=uuid.uuid4(), average_ticket_cents=rng.randint(0, 9999)) for _ in range(40)]
    previous = PreviousRun(frozenset(f.patient_id for f in items[:15]))

    def run(order):
        return {f.patient_id: analysis_points(f, "at_risk", None, S, NOW, NY, previous) for f in order}

    shuffled = list(items)
    rng.shuffle(shuffled)
    assert run(shuffled) == run(items)


# --- from real facts -------------------------------------------------------------------------


async def test_points_from_real_facts_and_staff_not_imported():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    botox = sc.service("Botox", "Injectables")
    no_staff = sc.provider("Dr Free", staff_active=None)
    p = sc.patient("seasonal")
    for day in (at(2024, 7, 10, 14), at(2025, 7, 12, 14), at(2025, 11, 4, 14), at(2026, 3, 2, 14)):
        sc.appt(p, "completed", day, botox, no_staff)
    await sc.save()

    async with tenant_session(tenant) as s:
        facts = await load_facts(s, NOW, TZ)
    f = facts[0]
    settings = with_points(seasonality=True)
    out = analysis_points(f, "dormant", "one_and_done", settings, NOW, TZ, None)
    assert out["provider_continuity"] == {"status": "unknown"}
    assert out["best_offer"]["service_id"] == botox.id
    assert out["best_time"]["visits_used"] == 4 and out["best_time"]["weekday"] is not None
    assert out["seasonality"]["applies"] is True  # July in two years, window June to August is near on 1 June
    assert out["change_since_last"] == {"change": "first_run"}
    assert data_available(facts) == {"staff": False, "memberships": False, "consents": False, "services": True}
    assert "revenue_at_risk" not in out  # dormant, not at risk


async def test_provider_continuity_from_real_staff_records():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    active = sc.provider("Active", staff_active=True)
    gone = sc.provider("Gone", staff_active=False)
    a, g = sc.patient("a"), sc.patient("g")
    sc.appt(a, "completed", at(2026, 3, 1), None, active)
    sc.appt(g, "completed", at(2026, 3, 1), None, gone)
    await sc.save()
    async with tenant_session(tenant) as s:
        facts = {f.patient_id: f for f in await load_facts(s, NOW, TZ)}
    assert provider_continuity(facts[a.id]) == {"status": "active"}
    assert provider_continuity(facts[g.id]) == {"status": "inactive"}
    assert data_available(facts.values())["staff"] is True
