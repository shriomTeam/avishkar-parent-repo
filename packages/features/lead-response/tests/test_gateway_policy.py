from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from clinic_lead_response.gateway.policy import (
    FIRST_INBOUND,
    Allow,
    Block,
    ConsentSnapshot,
    ConsentState,
    Defer,
    current_consent,
    decide,
    in_quiet_hours,
    quiet_hours_end,
)
from clinic_lead_response.gateway.types import REPLY_PURPOSES, BlockReason, Lane, Purpose
from clinic_lead_response.settings_model import LeadResponseQuietWindow

NY = ZoneInfo("America/New_York")
NIGHT = LeadResponseQuietWindow(start="21:00", end="08:00")  # crosses midnight
DAY = LeadResponseQuietWindow(start="12:00", end="13:00")  # inside one day
T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)

NONE = ConsentState()
FIRST = ConsentState(True, FIRST_INBOUND)
START = ConsentState(True, "start")
STAFF = ConsentState(True, "staff")
OUT = ConsentState(False, "stop")


def local(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=NY).astimezone(UTC)


def run(purpose, consent, *, now=None, quiet=NIGHT, lane=Lane.LIVE):
    return decide(
        purpose=purpose, lane=lane, now=now or local(2026, 5, 1, 23), tz=NY, quiet_hours=quiet, consent=consent
    )


# --- current consent ---------------------------------------------------------------------------------------------


def snap(granted, source, minutes):
    return ConsentSnapshot(granted, source, T0 + timedelta(minutes=minutes))


def test_no_records_means_no_state():
    assert current_consent([]) == ConsentState()


def test_the_newest_record_wins_whatever_the_input_order():
    records = [snap(True, "start", 5), snap(False, "stop", 9), snap(True, FIRST_INBOUND, 1)]
    assert current_consent(records) == ConsentState(False, "stop")
    assert current_consent(reversed(records)) == ConsentState(False, "stop")


def test_a_later_start_after_stop_grants_again():
    assert current_consent([snap(False, "stop", 1), snap(True, "start", 2)]) == ConsentState(True, "start")


def test_a_tie_is_won_by_the_revocation():
    records = [snap(True, "start", 3), snap(False, "stop", 3)]
    assert current_consent(records).granted is False
    assert current_consent(reversed(records)).granted is False


def test_a_tie_between_two_grants_is_still_a_grant():
    assert current_consent([snap(True, "start", 3), snap(True, "staff", 3)]).granted is True


# --- the decision ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", list(Purpose))
@pytest.mark.parametrize("lane", list(Lane))
def test_an_opted_out_contact_is_never_texted(purpose, lane):
    assert run(purpose, OUT, lane=lane) == Block(BlockReason.OPTED_OUT)


@pytest.mark.parametrize("purpose", sorted(REPLY_PURPOSES, key=str))
@pytest.mark.parametrize("consent", [NONE, FIRST, START, STAFF])
def test_a_reply_is_allowed_with_or_without_a_grant_and_inside_quiet_hours(purpose, consent):
    assert run(purpose, consent, now=local(2026, 5, 1, 23, 4)) == Allow()  # the chart's own 23:04 example


@pytest.mark.parametrize("consent", [NONE, FIRST])
def test_a_follow_up_needs_an_explicit_grant(consent):
    assert run(Purpose.FOLLOW_UP, consent) == Block(BlockReason.NO_CONSENT)


@pytest.mark.parametrize("consent", [START, STAFF, ConsentState(True, "import")])
def test_a_follow_up_with_an_explicit_grant_is_allowed_in_daytime(consent):
    assert run(Purpose.FOLLOW_UP, consent, now=local(2026, 5, 1, 10)) == Allow()


def test_a_follow_up_in_quiet_hours_waits_until_the_window_ends():
    decision = run(Purpose.FOLLOW_UP, START, now=local(2026, 5, 1, 23))
    assert decision == Defer(local(2026, 5, 2, 8))


def test_a_follow_up_after_midnight_waits_until_the_same_morning():
    decision = run(Purpose.FOLLOW_UP, START, now=local(2026, 5, 2, 3))
    assert decision == Defer(local(2026, 5, 2, 8))


def test_a_follow_up_with_no_quiet_hours_setting_is_never_deferred():
    assert run(Purpose.FOLLOW_UP, START, now=local(2026, 5, 1, 23), quiet=None) == Allow()


def test_the_bulk_lane_follows_follow_up_rules_even_for_a_reply_purpose():
    assert run(Purpose.ACK, NONE, lane=Lane.BULK) == Block(BlockReason.NO_CONSENT)
    assert run(Purpose.ACK, START, lane=Lane.BULK, now=local(2026, 5, 1, 23)) == Defer(local(2026, 5, 2, 8))


def test_a_follow_up_on_the_live_lane_still_needs_a_grant():
    assert run(Purpose.FOLLOW_UP, FIRST, lane=Lane.LIVE) == Block(BlockReason.NO_CONSENT)


# --- quiet hours -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hour", "minute", "quiet"),
    [(21, 0, True), (23, 59, True), (0, 0, True), (7, 59, True), (8, 0, False), (12, 0, False), (20, 59, False)],
)
def test_a_window_that_crosses_midnight(hour, minute, quiet):
    from datetime import time

    assert in_quiet_hours(time(hour, minute), NIGHT) is quiet


@pytest.mark.parametrize(("hour", "quiet"), [(11, False), (12, True), (12, True), (13, False)])
def test_a_window_inside_one_day_includes_its_start_and_excludes_its_end(hour, quiet):
    from datetime import time

    assert in_quiet_hours(time(hour, 0), DAY) is quiet


def test_the_clinic_time_zone_decides_not_the_servers():
    # 02:00 UTC on 2 May is 22:00 on 1 May in New York (inside quiet hours) but 19:00 in Los Angeles (outside).
    now = datetime(2026, 5, 2, 2, 0, tzinfo=UTC)
    ny = decide(purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP, now=now, tz=NY, quiet_hours=NIGHT, consent=START)
    la = decide(
        purpose=Purpose.FOLLOW_UP,
        lane=Lane.FOLLOW_UP,
        now=now,
        tz=ZoneInfo("America/Los_Angeles"),
        quiet_hours=NIGHT,
        consent=START,
    )
    assert isinstance(ny, Defer) and la == Allow()


# --- daylight saving edges (America/New_York: spring forward 2026-03-08, fall back 2026-11-01) -------------------


def test_the_morning_after_spring_forward_ends_at_08_00_local_which_is_12_00_utc():
    # 21:30 EST on 7 March; 8 March 08:00 is EDT (UTC-4), so the end is 12:00 UTC, not 13:00 UTC.
    end = quiet_hours_end(local(2026, 3, 7, 21, 30), NY, NIGHT)
    assert end == datetime(2026, 3, 8, 12, 0, tzinfo=UTC)


def test_the_morning_after_fall_back_ends_at_08_00_local_which_is_13_00_utc():
    end = quiet_hours_end(local(2026, 10, 31, 22, 0), NY, NIGHT)
    assert end == datetime(2026, 11, 1, 13, 0, tzinfo=UTC)  # 08:00 EST after the clocks went back


def test_a_window_ending_inside_the_spring_forward_gap_lands_after_the_gap():
    window = LeadResponseQuietWindow(start="21:00", end="02:30")  # 02:30 does not exist on 8 March
    end = quiet_hours_end(local(2026, 3, 7, 22, 0), NY, window)
    assert end == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)  # 03:30 EDT, the same distance after the gap


def test_a_window_ending_in_the_fall_back_hour_means_its_first_occurrence():
    window = LeadResponseQuietWindow(start="21:00", end="01:30")  # 01:30 happens twice on 1 November
    end = quiet_hours_end(local(2026, 10, 31, 22, 0), NY, window)
    assert end == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)  # 01:30 EDT, the first one


def test_the_deferred_time_is_always_after_now_and_in_utc():
    for hour in range(24):
        decision = run(Purpose.FOLLOW_UP, START, now=local(2026, 3, 7, hour))
        if isinstance(decision, Defer):
            assert decision.until > local(2026, 3, 7, hour) and decision.until.tzinfo is UTC
