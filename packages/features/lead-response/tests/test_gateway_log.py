import logging
import uuid

import pytest

from clinic_lead_response.gateway.log import ALLOWED_FIELDS, format_fields, log_event, mask_phone


@pytest.mark.parametrize(
    ("number", "masked"),
    [("+14155550123", "***23"), ("+442079460958", "***58"), ("4155550100", "***00"), ("+1 (415) 555-0142", "***42")],
)
def test_a_phone_number_is_masked_to_its_last_two_digits(number, masked):
    assert mask_phone(number) == masked


@pytest.mark.parametrize("number", [None, "", "12", "abc", "+1"])
def test_a_short_or_missing_number_is_fully_masked(number):
    assert mask_phone(number) == "***"


def test_the_masked_value_holds_nothing_but_two_digits():
    assert "415" not in mask_phone("+14155550123") and "+1" not in mask_phone("+14155550123")


def test_only_the_named_fields_can_be_logged():
    for forbidden in ("body", "to", "phone", "token", "auth_token", "text", "from_number"):
        assert forbidden not in ALLOWED_FIELDS
        with pytest.raises(ValueError):
            format_fields(**{forbidden: "x"})


def test_fields_come_out_sorted_and_none_is_left_out():
    assert format_fields(outcome="sent", tenant_id="t", attempt=1, reason=None) == "attempt=1 outcome=sent tenant_id=t"


def test_a_uuid_is_logged_whole_and_odd_characters_are_flattened():
    ident = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert format_fields(message_id=ident) == "message_id=12345678-1234-5678-1234-567812345678"
    assert format_fields(reason="line one\nline two with spaces") == "reason=line_one_line_two_with_spaces"


def test_a_long_value_is_cut(caplog):
    assert len(format_fields(reason="x" * 500)) < 80


def test_log_event_writes_one_line(caplog):
    logger = logging.getLogger("lead_response.gateway.test")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(logger, "send", outcome="sent", lane="live", to_masked=mask_phone("+14155550123"))
    assert [r.getMessage() for r in caplog.records] == ["send lane=live outcome=sent to_masked=***23"]
