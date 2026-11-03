"""STOP, START and HELP: stored like any text, acted on in a second transaction, no ack, no confirmation from us."""

import asyncio
import uuid

import pytest
from lr_gateway import audit_rows, consents, make_lead
from lr_intake import LEAD_NUMBER, OUR_NUMBER, Intake, count, rows, sid, twilio_pairs
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import ConsentRecord, Contact, Job, Message
from clinic_lead_response.gateway.keywords import START_KEYWORDS, STOP_KEYWORDS
from clinic_lead_response.gateway.service import Gateway
from clinic_lead_response.intake import service

EMPTY = '<?xml version="1.0" encoding="UTF-8"?><Response/>'


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def say(intake, tenant, word: str, n: int = 1, **kw):
    return await intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=word), **kw)


async def all_consent(tenant) -> list[ConsentRecord]:
    return await rows(tenant, ConsentRecord, ConsentRecord.created_at, ConsentRecord.id)


async def jobs(tenant) -> list[Job]:
    return await rows(tenant, Job)


@pytest.mark.parametrize("word", sorted(STOP_KEYWORDS))
async def test_every_stop_word_opts_the_contact_out_and_creates_no_job(intake, make_tenant, word):
    tenant = await make_tenant()
    response = await say(intake, tenant, word)
    assert response.status_code == 200 and response.text == EMPTY
    (message,) = await rows(tenant, Message)
    assert message.body == word and message.direction == "inbound"
    (consent,) = await all_consent(tenant)
    assert (consent.granted, consent.source, consent.channel) == (False, "stop", "sms")
    assert consent.message_id == message.id and consent.trace_id == message.trace_id
    assert await jobs(tenant) == []


@pytest.mark.parametrize("word", ["STOP", "  Stop\n", "StopAll", "UNSUBSCRIBE", "\tquit "])
async def test_case_and_surrounding_spaces_do_not_matter(intake, make_tenant, word):
    tenant = await make_tenant()
    assert (await say(intake, tenant, word)).status_code == 200
    assert [c.granted for c in await all_consent(tenant)] == [False]


@pytest.mark.parametrize("word", sorted(START_KEYWORDS))
async def test_every_start_word_grants_and_creates_no_job_and_no_first_inbound(intake, make_tenant, word):
    tenant = await make_tenant()
    response = await say(intake, tenant, word)
    assert response.status_code == 200 and response.text == EMPTY
    (consent,) = await all_consent(tenant)
    assert (consent.granted, consent.source) == (True, "start")
    assert await jobs(tenant) == []


async def test_start_after_stop_opts_the_contact_back_in(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP", 1)
    await say(intake, tenant, "START", 2)
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(False, "stop"), (True, "start")]


async def test_a_stop_from_a_contact_who_is_already_out_adds_nothing(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP", 1)
    await say(intake, tenant, "STOP", 2)
    assert len(await all_consent(tenant)) == 1 and await count(tenant, Message) == 2


async def test_a_stop_as_the_very_first_text_makes_the_contact_and_only_a_revocation(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP")
    assert await count(tenant, Contact) == 1
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(False, "stop")]


async def test_a_stop_from_a_known_contact_with_a_first_inbound_grant_revokes_it(intake, make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone=LEAD_NUMBER, consent=(True, "first_inbound"))
    await say(intake, tenant, "STOP")
    assert [(c.granted, c.source) for c in await consents(tenant, lead.contact)] == [
        (True, "first_inbound"),
        (False, "stop"),
    ]


async def test_help_is_stored_gets_a_help_job_and_no_ack(intake, make_tenant):
    tenant = await make_tenant()
    response = await say(intake, tenant, "HELP")
    assert response.status_code == 200 and response.text == EMPTY
    (message,) = await rows(tenant, Message)
    (job,) = await jobs(tenant)
    assert (job.kind, job.status) == ("help", "pending")
    assert job.idempotency_key == f"help:{message.id}"
    assert job.payload == {"message_id": str(message.id)}
    assert job.trace_id == message.trace_id and job.conversation_id == message.conversation_id
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(True, "first_inbound")]


async def test_help_from_a_contact_who_opted_out_changes_nothing_about_consent(intake, make_tenant):
    tenant = await make_tenant()
    lead = await make_lead(tenant, phone=LEAD_NUMBER, consent=(False, "stop"))
    await say(intake, tenant, "help")
    assert [(c.granted, c.source) for c in await consents(tenant, lead.contact)] == [(False, "stop")]
    assert [j.kind for j in await jobs(tenant)] == ["help"]  # the gateway refuses to send it; intake only queues


@pytest.mark.parametrize(
    "words", ["please stop", "STOP.", "stop it", "stopping", "yes please", "helpful", "I need help"]
)
async def test_a_text_that_only_contains_a_keyword_is_an_ordinary_text(intake, make_tenant, words):
    tenant = await make_tenant()
    await say(intake, tenant, words)
    assert [j.kind for j in await jobs(tenant)] == ["ack"]
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(True, "first_inbound")]


async def test_a_keyword_gets_no_ack_even_when_the_same_contact_texts_normally_too(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "Hi there", 1)
    await say(intake, tenant, "STOP", 2)
    assert [j.kind for j in await jobs(tenant)] == ["ack"]


async def test_an_ordinary_text_after_stop_is_kept_and_does_not_opt_the_contact_back_in(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP", 1)
    await say(intake, tenant, "Are you open Monday?", 2)
    assert await count(tenant, Message) == 2
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(False, "stop")]


async def test_a_keyword_is_never_throttled(intake, make_tenant):
    tenant = await make_tenant()
    for n in range(1, 26):
        assert (await say(intake, tenant, "STOP", n)).status_code == 200
    assert await count(tenant, Message) == 25 and await jobs(tenant) == []
    assert len(await all_consent(tenant)) == 1


async def test_one_stop_audit_row_holds_only_names(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP")
    (row,) = await audit_rows(tenant, "lead_response.consent.changed")
    assert row.actor_type == "system" and row.entity_type == "lead_response_consent"
    assert row.details == {"channel": "sms", "granted": False, "source": "stop"}


async def test_a_stop_in_one_clinic_does_not_opt_out_the_same_number_in_another(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_b = await make_lead(b, phone=LEAD_NUMBER, consent=(True, "first_inbound"))
    await say(intake, a, "STOP")
    assert [(c.granted, c.source) for c in await consents(b, lead_b.contact)] == [(True, "first_inbound")]
    assert await count(b, Message) == 0


async def test_a_clinic_without_the_feature_runs_no_keyword(monkeypatch, make_tenant):
    tenant = await make_tenant(())
    calls = []

    async def spy(self, *a, **k):
        calls.append(1)

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", spy)
    assert (await say(Intake(monkeypatch), tenant, "STOP")).status_code == 200
    assert calls == [] and await count(tenant, ConsentRecord) == 0


# --- the second transaction: after the commit, before the answer -------------------------------------------------


async def test_the_text_is_already_committed_when_the_keyword_runs_and_the_answer_waits_for_it(
    intake, make_tenant, monkeypatch
):
    tenant = await make_tenant()
    real = Gateway.handle_inbound_keyword
    seen = {}

    async def watch(self, tenant_id, **kwargs):
        seen["messages_when_it_starts"] = await count(tenant_id, Message)  # another connection: only committed rows
        seen["consents_when_it_starts"] = await count(tenant_id, ConsentRecord)
        result = await real(self, tenant_id, **kwargs)
        await asyncio.sleep(0.3)
        seen["finished"] = True
        return result

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", watch)
    response = await say(intake, tenant, "STOP")
    assert response.status_code == 200
    assert seen == {"messages_when_it_starts": 1, "consents_when_it_starts": 0, "finished": True}


async def test_the_keyword_handler_gets_the_ids_and_the_text_it_needs(intake, make_tenant, monkeypatch):
    tenant = await make_tenant()
    got = {}

    async def spy(self, tenant_id, **kwargs):
        got.update(tenant_id=tenant_id, **kwargs)
        return None

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", spy)
    await say(intake, tenant, "STOP")
    (message,) = await rows(tenant, Message)
    assert got["tenant_id"] == tenant and got["text"] == "STOP" and got["inbound_message_id"] == message.id
    assert got["contact_id"] == (await rows(tenant, Contact))[0].id and got["trace_id"] == message.trace_id


@pytest.mark.parametrize("word", ["STOP", "START", "HELP"])
async def test_a_failing_handler_gives_500_and_the_retry_recovers(intake, make_tenant, monkeypatch, word):
    tenant = await make_tenant()
    real = Gateway.handle_inbound_keyword
    calls = []

    async def fail_once(self, tenant_id, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the database went away")
        return await real(self, tenant_id, **kwargs)

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", fail_once)
    failed = await say(intake, tenant, word, raise_app_exceptions=False)
    assert failed.status_code == 500 and failed.content == b""
    assert await count(tenant, Message) == 1  # the text itself is kept
    assert await count(tenant, ConsentRecord) == (1 if word == "HELP" else 0)  # HELP's only record is the first grant
    retried = await say(intake, tenant, word)
    assert retried.status_code == 200 and retried.text == EMPTY
    # STOP and START are recovered by running the handler again. HELP has nothing to recover: its job was queued
    # with the text, and the first-inbound grant written then already refers to the message, so the retry skips it.
    assert len(calls) == (1 if word == "HELP" else 2) and await count(tenant, Message) == 1
    effect = {"STOP": [(False, "stop")], "START": [(True, "start")], "HELP": [(True, "first_inbound")]}[word]
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == effect
    assert len(await jobs(tenant)) == (1 if word == "HELP" else 0)


async def test_the_recovered_stop_is_linked_to_the_one_stored_message(intake, make_tenant, monkeypatch):
    tenant = await make_tenant()
    real = Gateway.handle_inbound_keyword
    calls = []

    async def fail_once(self, tenant_id, **kwargs):
        calls.append(kwargs["inbound_message_id"])
        if len(calls) == 1:
            raise RuntimeError("boom")
        return await real(self, tenant_id, **kwargs)

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", fail_once)
    await say(intake, tenant, "STOP", raise_app_exceptions=False)
    await say(intake, tenant, "STOP")
    (message,) = await rows(tenant, Message)
    (consent,) = await all_consent(tenant)
    assert consent.message_id == message.id
    assert calls == [message.id, message.id]  # the retry found the stored text and applied it to that same message


async def test_the_failure_is_logged_without_the_error_text_or_any_personal_value(
    intake, make_tenant, monkeypatch, caplog
):
    tenant = await make_tenant()

    async def fail(self, tenant_id, **kwargs):
        raise RuntimeError(f"cannot reach {LEAD_NUMBER} {OUR_NUMBER} Zebra-Quartz")

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", fail)
    caplog.set_level("DEBUG", logger="lead_response")
    await say(intake, tenant, "STOP", raise_app_exceptions=False)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "keyword_failed" in text and f"tenant_id={tenant}" in text and "trace_id=" in text
    assert LEAD_NUMBER not in text and LEAD_NUMBER[1:] not in text and "Zebra-Quartz" not in text


async def test_an_ordinary_text_never_runs_the_keyword_handler(intake, make_tenant, monkeypatch):
    tenant = await make_tenant()
    calls = []

    async def spy(self, *a, **k):
        calls.append(1)

    monkeypatch.setattr(Gateway, "handle_inbound_keyword", spy)
    await say(intake, tenant, "Hello, are you open?")
    assert calls == []


# --- retries ----------------------------------------------------------------------------------------------------


async def test_a_retry_of_a_finished_stop_makes_nothing_new(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP")
    again = await say(intake, tenant, "STOP")
    assert again.status_code == 200
    assert await count(tenant, Message) == 1 and len(await all_consent(tenant)) == 1 and await jobs(tenant) == []


async def test_a_late_retry_of_stop_does_not_undo_a_start_sent_since(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP", 1)
    await say(intake, tenant, "START", 2)
    await say(intake, tenant, "STOP", 1)  # Twilio delivers the first STOP again, late
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(False, "stop"), (True, "start")]


async def test_a_retry_of_a_stop_that_changed_nothing_does_not_undo_a_later_start(intake, make_tenant):
    tenant = await make_tenant()
    await say(intake, tenant, "STOP", 1)
    await say(intake, tenant, "STOP", 2)  # already out: changes nothing, links no consent record
    await say(intake, tenant, "START", 3)
    await say(intake, tenant, "STOP", 2)  # late retry of the second one
    assert [(c.granted, c.source) for c in await all_consent(tenant)] == [(False, "stop"), (True, "start")]


async def test_ten_copies_of_a_stop_at_once_make_one_revocation(intake, make_tenant):
    tenant = await make_tenant()
    responses = await asyncio.gather(*[say(intake, tenant, "STOP") for _ in range(10)])
    assert [r.status_code for r in responses] == [200] * 10
    assert await count(tenant, Message) == 1
    assert [c.granted for c in await all_consent(tenant)] == [False]


async def test_what_the_service_reports_for_keywords(make_tenant):
    from clinic_lead_response.gateway.keywords import Keyword
    from clinic_lead_response.intake.parse import InboundText

    tenant = await make_tenant()

    def text(n, body):
        return InboundText(sid(n), LEAD_NUMBER, OUR_NUMBER, body)

    stop = await service.accept(tenant, text(1, "STOP"), trace_id=uuid.uuid4())
    assert (stop.keyword, stop.keyword_pending, stop.ack_queued, stop.help_queued) == (Keyword.STOP, True, False, False)
    help_ = await service.accept(tenant, text(2, "help"), trace_id=uuid.uuid4())
    assert (help_.keyword, help_.keyword_pending, help_.ack_queued, help_.help_queued) == (
        Keyword.HELP,
        True,
        False,
        True,
    )
    plain = await service.accept(tenant, text(3, "hello"), trace_id=uuid.uuid4())
    assert (plain.keyword, plain.keyword_pending, plain.ack_queued) == (None, False, True)
    async with tenant_session(tenant) as session:
        assert await session.scalar(select(Message.id).where(Message.provider_message_id == sid(1)))
