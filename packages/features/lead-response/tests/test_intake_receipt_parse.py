"""Reading a Twilio status callback. Pure tests: no database, no network."""

import pytest
from lr_intake import SID, receipt_pairs

from clinic_lead_response.intake.parse import MAX_FIELDS, Malformed, Receipt, parse_receipt


def test_a_normal_receipt_is_read():
    assert parse_receipt(receipt_pairs(SID, "delivered")) == Receipt(SID, "delivered", None)


@pytest.mark.parametrize(
    "status", ["queued", "sending", "sent", "delivered", "undelivered", "failed", "read", "canceled", "receiving"]
)
def test_every_status_word_twilio_uses_is_read_as_it_comes(status):
    assert parse_receipt(receipt_pairs(SID, status)).status == status


def test_an_error_code_is_read_as_a_number():
    assert parse_receipt(receipt_pairs(SID, "failed", ErrorCode="30003")).error_code == 30003
    assert parse_receipt(receipt_pairs(SID, "undelivered", ErrorCode="21610")).error_code == 21610


@pytest.mark.parametrize("code", ["", "abc", "-1", "1.5", "1234567", "21610 ", " 21610", "２１６１０", "0x10"])
def test_an_error_code_we_cannot_read_is_left_out_and_the_receipt_is_kept(code):
    assert parse_receipt(receipt_pairs(SID, "failed", ErrorCode=code)) == Receipt(SID, "failed", None)


@pytest.mark.parametrize("sid", ["", "SM", "SM" + "0" * 31, "XX" + "0" * 32, "SM" + "0" * 32 + "\n"])
def test_a_bad_message_sid_is_malformed(sid):
    with pytest.raises(Malformed) as caught:
        parse_receipt(receipt_pairs(sid))
    assert caught.value.reason == "bad_message_sid"


@pytest.mark.parametrize("status", ["", "sent!", "a b", "x" * 33, "sent\n", "délivré", "1"])
def test_a_status_that_is_not_a_plain_word_is_malformed(status):
    with pytest.raises(Malformed) as caught:
        parse_receipt(receipt_pairs(SID, status))
    assert caught.value.reason == "bad_status"


@pytest.mark.parametrize("missing", ["MessageSid", "MessageStatus"])
def test_a_missing_required_field_is_malformed(missing):
    with pytest.raises(Malformed):
        parse_receipt(receipt_pairs(SID, **{missing: None}))


@pytest.mark.parametrize("name", ["MessageSid", "MessageStatus", "ErrorCode"])
def test_a_repeated_field_we_read_is_malformed(name):
    with pytest.raises(Malformed) as caught:
        parse_receipt(receipt_pairs(SID, "failed", ErrorCode="30003") + [(name, "again")])
    assert caught.value.reason == "duplicate_field"


def test_the_sms_status_alias_alone_is_not_enough():
    with pytest.raises(Malformed):
        parse_receipt(receipt_pairs(SID, MessageStatus=None))


def test_the_field_count_limit():
    base = receipt_pairs(SID)
    ok = base + [(f"F{i}", "1") for i in range(MAX_FIELDS - len(base))]
    parse_receipt(ok)
    with pytest.raises(Malformed) as caught:
        parse_receipt(ok + [("One", "more")])
    assert caught.value.reason == "too_many_fields"


def test_the_numbers_in_a_receipt_are_never_read():
    note = parse_receipt(receipt_pairs(SID, From="+14155550100", To="+14155550142"))
    assert "+1415" not in repr(note)
