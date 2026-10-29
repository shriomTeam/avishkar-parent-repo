"""Every rule on the settings, on the model alone (no database)."""

import pytest
from pydantic import ValidationError

from clinic_lead_response.settings_model import (
    ACK_MAX_LENGTH,
    LeadResponseBusinessHours,
    LeadResponseCapabilities,
    LeadResponseSettings,
)


def valid(**overrides):
    return LeadResponseSettings.model_validate(overrides)


def invalid(match: str | None = None, **overrides):
    with pytest.raises(ValidationError) as error:
        LeadResponseSettings.model_validate(overrides)
    if match:
        assert match in str(error.value)


def test_the_defaults():
    s = LeadResponseSettings()
    assert (s.holding_minutes, s.sla_minutes, s.send_mode, s.ai_active_mode) == (15, 30, "draft", "always")
    assert s.ai_enabled is False and not any(s.capabilities.model_dump().values())
    assert s.escalation_role == "office_manager" and s.quiet_hours is None and s.business_hours.stored() == {}
    assert not s.uses_ai()


@pytest.mark.parametrize("minutes", [5, 6, 59, 60])
def test_holding_inside_the_range(minutes):
    assert valid(holding_minutes=minutes, sla_minutes=100).holding_minutes == minutes


@pytest.mark.parametrize("minutes", [4, 0, -1, 61])
def test_holding_outside_the_range(minutes):
    invalid("holding_minutes", holding_minutes=minutes, sla_minutes=100)


@pytest.mark.parametrize("minutes", [10, 11, 239, 240])
def test_sla_inside_the_range(minutes):
    assert valid(holding_minutes=5, sla_minutes=minutes).sla_minutes == minutes


@pytest.mark.parametrize("minutes", [9, 0, 241])
def test_sla_outside_the_range(minutes):
    invalid("sla_minutes", holding_minutes=5, sla_minutes=minutes)


@pytest.mark.parametrize(("holding", "sla"), [(30, 30), (40, 30), (60, 60), (59, 40)])
def test_sla_must_be_longer_than_holding(holding, sla):
    invalid("longer than the holding", holding_minutes=holding, sla_minutes=sla)


def test_sla_just_longer_than_holding_is_accepted():
    assert valid(holding_minutes=29, sla_minutes=30).sla_minutes == 30


def test_overflow_needs_minutes_and_only_overflow_takes_them():
    invalid("overflow needs", ai_active_mode="overflow")
    invalid("only apply to the overflow", ai_active_mode="always", overflow_minutes=10)
    invalid("only apply to the overflow", ai_active_mode="after_hours", overflow_minutes=10)
    assert valid(ai_active_mode="overflow", overflow_minutes=10).overflow_minutes == 10
    assert valid(ai_active_mode="after_hours").overflow_minutes is None


@pytest.mark.parametrize("minutes", [0, -5, 241])
def test_overflow_minutes_range(minutes):
    invalid(ai_active_mode="overflow", overflow_minutes=minutes)


@pytest.mark.parametrize("minutes", [1, 240])
def test_overflow_minutes_edges(minutes):
    assert valid(ai_active_mode="overflow", overflow_minutes=minutes).overflow_minutes == minutes


@pytest.mark.parametrize("mode", ["", "sometimes", "ALWAYS"])
def test_unknown_ai_mode(mode):
    invalid(ai_active_mode=mode)


@pytest.mark.parametrize(
    "text", ["x", "Thanks for texting. We will reply soon.", "a" * ACK_MAX_LENGTH, "Line one\nLine two"]
)
def test_ack_text_accepted(text):
    assert valid(ack_text=text).ack_text == text


def test_ack_text_is_trimmed():
    assert valid(ack_text="  Hello there  \n").ack_text == "Hello there"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   \n ",
        "a" * (ACK_MAX_LENGTH + 1),
        "Hi {first_name}",
        "Hi {{first_name}}",
        "Hi }",
        "bell\x07",
        "tab\there",
        "null\x00byte",
        "zero​width",
        "bidi\u202eoverride",
        "privateuse",
    ],
)
def test_ack_text_rejected(text):
    invalid("ack_text", ack_text=text)


def test_a_rejected_ack_text_is_not_in_the_error_message_we_write():
    with pytest.raises(ValidationError) as error:
        valid(ack_text="Dr Smith {secret}")
    assert all("Smith" not in e["msg"] for e in error.value.errors())


@pytest.mark.parametrize("role", ["owner", "office_manager"])
def test_escalation_roles_accepted(role):
    assert valid(escalation_role=role).escalation_role == role


@pytest.mark.parametrize("role", ["front_desk", "consultant", "provider", "admin", ""])
def test_escalation_roles_rejected(role):
    invalid("escalation_role", escalation_role=role)


@pytest.mark.parametrize("mode", ["manual", "", "DRAFT"])
def test_unknown_send_mode(mode):
    invalid("send_mode", send_mode=mode)


@pytest.mark.parametrize(
    "overrides",
    [
        {"surprise": 1},
        {"capabilities": {"answer_questions": False, "mind_reading": True}},
        {"business_hours": {"monday": []}},
        {"business_hours": {"mon": [{"start": "09:00", "end": "17:00", "note": "x"}]}},
        {"quiet_hours": {"start": "21:00", "end": "08:00", "note": "x"}},
    ],
)
def test_unknown_keys_are_rejected_everywhere(overrides):
    invalid(**overrides)


@pytest.mark.parametrize(
    "overrides", [{"holding_minutes": "15"}, {"holding_minutes": True}, {"ai_enabled": 1}, {"ai_enabled": "false"}]
)
def test_types_are_strict(overrides):
    invalid(**overrides)


def test_booking_needs_open_slots():
    with pytest.raises(ValidationError, match="book_appointments needs show_open_slots"):
        LeadResponseCapabilities(book_appointments=True)
    with pytest.raises(ValidationError, match="needs show_open_slots"):
        LeadResponseCapabilities(book_appointments=True, show_open_slots=False)
    assert LeadResponseCapabilities(book_appointments=True, show_open_slots=True).book_appointments
    invalid("needs show_open_slots", capabilities={"book_appointments": True})
    assert valid(capabilities={"book_appointments": True, "show_open_slots": True}).uses_ai()


@pytest.mark.parametrize("time", ["9:00", "24:00", "09:60", "0900", "09:00:00", "", "ab:cd"])
def test_bad_clock_times(time):
    invalid(business_hours={"mon": [{"start": time, "end": "17:00"}]})


@pytest.mark.parametrize(("start", "end"), [("17:00", "09:00"), ("09:00", "09:00")])
def test_business_window_start_before_end(start, end):
    invalid("start must be before end", business_hours={"tue": [{"start": start, "end": end}]})


def test_business_windows_must_not_overlap_but_may_touch():
    invalid("overlap", business_hours={"wed": [{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "17:00"}]})
    touching = {"wed": [{"start": "13:00", "end": "17:00"}, {"start": "09:00", "end": "13:00"}]}
    hours = valid(business_hours=touching).business_hours
    assert [w.start for w in hours.wed] == ["09:00", "13:00"]  # stored in order


def test_at_most_three_windows_a_day():
    three = [{"start": f"{h:02d}:00", "end": f"{h:02d}:30"} for h in (8, 10, 12)]
    assert len(valid(business_hours={"thu": three}).business_hours.thu) == 3
    invalid(business_hours={"thu": [*three, {"start": "14:00", "end": "15:00"}]})


def test_only_days_with_windows_are_stored():
    hours = LeadResponseBusinessHours.model_validate({"mon": [{"start": "09:00", "end": "17:00"}], "sun": []})
    assert hours.stored() == {"mon": [{"start": "09:00", "end": "17:00"}]}


def test_quiet_hours_may_cross_midnight_but_not_be_empty():
    assert valid(quiet_hours={"start": "21:00", "end": "08:00"}).quiet_hours.end == "08:00"
    assert valid(quiet_hours={"start": "08:00", "end": "21:00"}).quiet_hours.start == "08:00"
    assert valid(quiet_hours=None).quiet_hours is None
    invalid("differ", quiet_hours={"start": "21:00", "end": "21:00"})
    invalid(quiet_hours={"start": "25:00", "end": "08:00"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"ai_enabled": True},
        {"send_mode": "auto"},
        {"capabilities": {"answer_questions": True}},
        {"capabilities": {"quote_pricing": True}},
        {"capabilities": {"show_open_slots": True}},
        {"capabilities": {"show_open_slots": True, "book_appointments": True}},
        {"capabilities": {"patient_aware_replies": True}},
    ],
)
def test_anything_that_turns_the_ai_on_is_flagged(overrides):
    assert valid(**overrides).uses_ai()


def test_ai_modes_and_hours_alone_do_not_count_as_using_ai():
    assert not valid(ai_active_mode="after_hours", quiet_hours={"start": "21:00", "end": "08:00"}).uses_ai()
