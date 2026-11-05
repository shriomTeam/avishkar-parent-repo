"""Odd input from a signed request: what is stored, what is cut, and what is refused."""

import pytest
from lr_intake import BODY, Intake, count, form_bytes, rows, sid, twilio_pairs

from clinic_db.models.lead_response import ConsentRecord, Contact, Job, Message
from clinic_lead_response.intake.parse import MAX_FIELDS, MAX_TEXT_CHARS


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def only_message(tenant) -> Message:
    (message,) = await rows(tenant, Message)
    return message


async def test_a_nul_byte_is_removed_and_the_text_is_stored(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant, twilio_pairs(Body="before\x00after"))
    assert response.status_code == 200
    assert (await only_message(tenant)).body == "beforeafter"


async def test_bad_utf8_is_stored_with_replacement_characters(intake, make_tenant):
    tenant = await make_tenant()
    raw = form_bytes(twilio_pairs(Body="x")).replace(b"Body=x", b"Body=ok%FF%FEend")
    response = await intake.post(tenant, raw=raw)
    assert response.status_code == 200
    body = (await only_message(tenant)).body
    assert body.startswith("ok") and body.endswith("end") and "�" in body


async def test_a_very_long_text_is_cut_at_1600_characters(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant, twilio_pairs(Body="x" * 5000))
    assert response.status_code == 200
    assert len((await only_message(tenant)).body) == MAX_TEXT_CHARS


async def test_an_empty_body_is_stored_as_an_empty_text(intake, make_tenant):
    tenant = await make_tenant()
    assert (await intake.post(tenant, twilio_pairs(Body=""))).status_code == 200
    assert (await only_message(tenant)).body == ""


async def test_a_missing_body_is_stored_as_an_empty_text(intake, make_tenant):
    tenant = await make_tenant()
    assert (await intake.post(tenant, twilio_pairs(Body=None))).status_code == 200
    assert (await only_message(tenant)).body == ""


async def test_emoji_and_non_latin_text_survive(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant, twilio_pairs(Body="Hi 😀 ñ 日本語 ✓"))
    assert (await only_message(tenant)).body == "Hi 😀 ñ 日本語 ✓"


async def test_spaces_and_line_breaks_are_kept_as_sent(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant, twilio_pairs(Body="  two\nlines  "))
    assert (await only_message(tenant)).body == "  two\nlines  "


async def test_a_picture_message_stores_its_words_and_no_media(intake, make_tenant):
    tenant = await make_tenant()
    pairs = twilio_pairs(NumMedia="1", Body="see photo") + [
        ("MediaUrl0", "https://api.twilio.com/media/ME1"),
        ("MediaContentType0", "image/jpeg"),
    ]
    assert (await intake.post(tenant, pairs)).status_code == 200
    message = await only_message(tenant)
    assert message.body == "see photo"
    assert "twilio.com/media" not in message.body


async def test_unknown_extra_fields_are_ignored(intake, make_tenant):
    tenant = await make_tenant()
    assert (await intake.post(tenant, twilio_pairs() + [("FromCity", "X"), ("Zzz", "1")])).status_code == 200
    assert (await only_message(tenant)).body == BODY


async def test_exactly_the_field_limit_is_accepted(intake, make_tenant):
    tenant = await make_tenant()
    base = twilio_pairs()
    pairs = base + [(f"F{i}", "1") for i in range(MAX_FIELDS - len(base))]
    assert (await intake.post(tenant, pairs)).status_code == 200
    assert await count(tenant, Message) == 1


async def test_one_field_over_the_limit_is_400_and_stores_nothing(intake, make_tenant):
    tenant = await make_tenant()
    base = twilio_pairs()
    pairs = base + [(f"F{i}", "1") for i in range(MAX_FIELDS - len(base) + 1)]
    response = await intake.post(tenant, pairs)
    assert response.status_code == 400
    assert await count(tenant, Message) == 0 and await count(tenant, Contact) == 0


@pytest.mark.parametrize("name", ["MessageSid", "From", "To", "Body"])
async def test_a_repeated_field_we_read_is_400(intake, make_tenant, name):
    tenant = await make_tenant()
    response = await intake.post(tenant, twilio_pairs() + [(name, "again")])
    assert response.status_code == 400
    assert await count(tenant, Message) == 0


async def test_a_signed_empty_form_is_400(intake, make_tenant):
    tenant = await make_tenant()
    response = await intake.post(tenant, raw=b"")
    assert response.status_code == 400
    assert await count(tenant, Message) == 0


async def test_a_refused_text_leaves_no_half_written_rows(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant, twilio_pairs(MessageSid="bad"))
    await intake.post(tenant, twilio_pairs(From="12345"))
    for model in (Message, Contact, ConsentRecord, Job):
        assert await count(tenant, model) == 0


async def test_a_sid_with_the_media_prefix_is_accepted(intake, make_tenant):
    tenant = await make_tenant()
    assert (await intake.post(tenant, twilio_pairs(MessageSid="MM" + "0" * 32))).status_code == 200
    assert (await only_message(tenant)).provider_message_id == "MM" + "0" * 32


async def test_the_next_text_after_a_refused_one_is_stored_normally(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant, twilio_pairs(MessageSid="bad"))
    assert (await intake.post(tenant, twilio_pairs(MessageSid=sid(5)))).status_code == 200
    assert await count(tenant, Message) == 1
