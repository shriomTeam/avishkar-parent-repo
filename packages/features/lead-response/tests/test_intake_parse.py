"""Reading a Twilio form post. Pure tests: no database, no network."""

import pytest
from lr_intake import BODY, LEAD_NUMBER, OUR_NUMBER, SID, form_bytes, twilio_pairs

from clinic_lead_response.intake.parse import (
    MAX_BODY_BYTES,
    MAX_FIELDS,
    MAX_TEXT_CHARS,
    Dropped,
    InboundText,
    Malformed,
    parse_form,
    parse_inbound,
)


def test_a_normal_text_is_read():
    text = parse_inbound(parse_form(form_bytes(twilio_pairs())))
    assert text == InboundText(SID, LEAD_NUMBER, OUR_NUMBER, BODY)


def test_the_limits_are_the_ones_planned():
    assert (MAX_BODY_BYTES, MAX_FIELDS, MAX_TEXT_CHARS) == (32 * 1024, 64, 1600)


def test_the_form_keeps_blank_values_repeated_names_and_order():
    assert parse_form(b"a=1&b=&a=2&c") == [("a", "1"), ("b", ""), ("a", "2"), ("c", "")]


def test_the_form_decodes_plus_and_percent():
    assert parse_form(b"Body=a+b%2B%C3%A9%25") == [("Body", "a b+é%")]


def test_an_empty_form_has_no_fields():
    assert parse_form(b"") == []


def test_bad_utf8_is_replaced_not_raised():
    ((name, value),) = parse_form(b"Body=%FF%FEab")
    assert name == "Body" and value.endswith("ab") and "�" in value


def test_unknown_fields_and_media_are_ignored():
    text = parse_inbound(twilio_pairs(NumMedia="2") + [("MediaUrl0", "https://x.test/a.jpg"), ("Extra", "1")])
    assert text.body == BODY


@pytest.mark.parametrize("sid", ["SM" + "0" * 32, "MM" + "f" * 32, "SM" + "A" * 32])
def test_message_and_media_sids_are_accepted(sid):
    assert parse_inbound(twilio_pairs(MessageSid=sid)).message_sid == sid


@pytest.mark.parametrize(
    "sid",
    [
        "",
        "SM",
        "SM" + "0" * 31,
        "SM" + "0" * 33,
        "XX" + "0" * 32,
        "sm" + "0" * 32,
        "SM" + "g" * 32,
        "SM" + "0" * 32 + "\n",
    ],
)
def test_a_bad_message_sid_is_malformed(sid):
    with pytest.raises(Malformed) as caught:
        parse_inbound(twilio_pairs(MessageSid=sid))
    assert caught.value.reason == "bad_message_sid"


@pytest.mark.parametrize("missing", ["MessageSid", "From", "To"])
def test_a_missing_required_field_is_malformed(missing):
    with pytest.raises(Malformed):
        parse_inbound(twilio_pairs(**{missing: None}))


def test_a_repeated_required_field_is_malformed():
    with pytest.raises(Malformed) as caught:
        parse_inbound(twilio_pairs() + [("From", "+14155550199")])
    assert caught.value.reason == "duplicate_field"


def test_a_repeated_field_we_do_not_read_is_fine():
    assert parse_inbound(twilio_pairs() + [("Extra", "1"), ("Extra", "2")]).body == BODY


@pytest.mark.parametrize(
    "sender",
    [
        "",
        "12345",
        "+0155555012",
        "+1",
        "+1415555",
        "+14155550142\n",
        "4155550142",
        "14155550142",
        "whatsapp:+14155550142",
        "+1 415 555 0142",
        "(415) 555-0142",
        "AcmeBank",
        "+1415555014212345",
    ],
)
def test_a_sender_that_is_not_e164_is_dropped_not_rejected(sender):
    with pytest.raises(Dropped) as caught:
        parse_inbound(twilio_pairs(From=sender))
    assert caught.value.reason == "sender_not_e164"


@pytest.mark.parametrize("recipient", ["", "whatsapp:+14155550100", "4155550100", "+14155550100 "])
def test_a_recipient_that_is_not_e164_is_dropped(recipient):
    with pytest.raises(Dropped) as caught:
        parse_inbound(twilio_pairs(To=recipient))
    assert caught.value.reason == "recipient_not_e164"


def test_a_missing_body_is_an_empty_text():
    assert parse_inbound(twilio_pairs(Body=None)).body == ""


def test_an_empty_body_is_kept_empty():
    assert parse_inbound(twilio_pairs(Body="")).body == ""


def test_the_text_is_kept_as_sent():
    assert parse_inbound(twilio_pairs(Body="  Hi\n\tthere  ✓ 😀 ")).body == "  Hi\n\tthere  ✓ 😀 "


def test_nul_bytes_are_removed():
    assert parse_inbound(twilio_pairs(Body="a\x00b\x00")).body == "ab"


def test_a_long_text_is_cut_at_the_limit_never_rejected():
    assert len(parse_inbound(twilio_pairs(Body="x" * MAX_TEXT_CHARS)).body) == MAX_TEXT_CHARS
    assert len(parse_inbound(twilio_pairs(Body="x" * (MAX_TEXT_CHARS + 1))).body) == MAX_TEXT_CHARS
    assert len(parse_inbound(twilio_pairs(Body="😀" * 5000)).body) == MAX_TEXT_CHARS


def test_the_field_count_limit():
    base = twilio_pairs()
    ok = base + [(f"F{i}", "1") for i in range(MAX_FIELDS - len(base))]
    assert len(ok) == MAX_FIELDS
    parse_inbound(ok)
    with pytest.raises(Malformed) as caught:
        parse_inbound(ok + [("One", "more")])
    assert caught.value.reason == "too_many_fields"


def test_what_is_read_cannot_leak_through_repr_or_an_error():
    text = parse_inbound(twilio_pairs())
    assert LEAD_NUMBER not in repr(text) and BODY not in repr(text) and OUR_NUMBER not in repr(text)
    with pytest.raises(Dropped) as caught:
        parse_inbound(twilio_pairs(From="+0" + "9" * 9, Body=BODY))
    assert BODY not in str(caught.value) and "9999" not in str(caught.value)
