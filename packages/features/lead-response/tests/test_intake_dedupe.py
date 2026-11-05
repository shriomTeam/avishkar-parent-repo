"""Twilio retries a webhook it did not get an answer to: the same MessageSid must never make a second message."""

import asyncio

import pytest
from lr_gateway import make_lead
from lr_intake import BODY, LEAD_NUMBER, Intake, count, rows, sid, twilio_pairs

from clinic_db.models.lead_response import ConsentRecord, Contact, Conversation, Job, Message
from clinic_lead_response.intake import store


@pytest.fixture
def intake(monkeypatch):
    return Intake(monkeypatch)


async def totals(tenant) -> dict[str, int]:
    return {m.__name__: await count(tenant, m) for m in (Message, Job, Contact, Conversation, ConsentRecord)}


async def test_a_repeated_delivery_is_one_message_and_one_job(intake, make_tenant):
    tenant = await make_tenant()
    first = await intake.post(tenant)
    again = await intake.post(tenant)
    assert (first.status_code, again.status_code) == (200, 200)
    assert first.text == again.text
    assert await totals(tenant) == {"Message": 1, "Job": 1, "Contact": 1, "Conversation": 1, "ConsentRecord": 1}


async def test_the_first_copy_is_the_one_that_is_kept(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant, twilio_pairs(Body="the first wording"))
    await intake.post(tenant, twilio_pairs(Body="a changed wording"))
    (message,) = await rows(tenant, Message)
    assert message.body == "the first wording"


async def test_many_retries_in_a_row_still_make_one_message(intake, make_tenant):
    tenant = await make_tenant()
    for _ in range(6):
        assert (await intake.post(tenant)).status_code == 200
    assert await count(tenant, Message) == 1 and await count(tenant, Job) == 1


async def test_different_sids_are_different_messages(intake, make_tenant):
    tenant = await make_tenant()
    for n in range(1, 4):
        await intake.post(tenant, twilio_pairs(MessageSid=sid(n)))
    assert await totals(tenant) == {"Message": 3, "Job": 3, "Contact": 1, "Conversation": 1, "ConsentRecord": 1}


async def test_a_retry_arriving_while_the_first_is_still_open_makes_one_message(intake, make_tenant, monkeypatch):
    """Ten copies at once. The first holds its transaction open after inserting; the others reach the message insert,
    wait on the unique key, and find the row once the first commits."""
    tenant = await make_tenant()
    await make_lead(tenant, phone=LEAD_NUMBER)  # the contact exists, so the copies race on the message itself
    real = store.insert_inbound

    async def slow(*args, **kwargs):
        result = await real(*args, **kwargs)
        await asyncio.sleep(0.4)  # the winner keeps its transaction open for a while
        return result

    monkeypatch.setattr(store, "insert_inbound", slow)
    responses = await asyncio.gather(*[intake.post(tenant) for _ in range(10)])
    assert [r.status_code for r in responses] == [200] * 10
    assert await totals(tenant) == {"Message": 1, "Job": 1, "Contact": 1, "Conversation": 1, "ConsentRecord": 1}


async def test_ten_copies_of_a_first_ever_text_make_one_of_everything(intake, make_tenant):
    tenant = await make_tenant()
    responses = await asyncio.gather(*[intake.post(tenant) for _ in range(10)])
    assert [r.status_code for r in responses] == [200] * 10
    assert await totals(tenant) == {"Message": 1, "Job": 1, "Contact": 1, "Conversation": 1, "ConsentRecord": 1}


async def test_ten_different_texts_from_one_new_number_make_one_contact(intake, make_tenant):
    tenant = await make_tenant()
    responses = await asyncio.gather(
        *[intake.post(tenant, twilio_pairs(MessageSid=sid(n), Body=f"text {n}")) for n in range(1, 11)]
    )
    assert [r.status_code for r in responses] == [200] * 10
    totals_now = await totals(tenant)
    assert totals_now["Contact"] == 1 and totals_now["Conversation"] == 1
    assert totals_now["Message"] == 10 and totals_now["Job"] == 10
    assert totals_now["ConsentRecord"] >= 1  # at most one per request that raced; never more than the messages


async def test_a_failure_before_the_commit_leaves_nothing_and_the_retry_is_stored(intake, make_tenant, monkeypatch):
    tenant = await make_tenant()
    real = store.queue_ack
    calls = []

    async def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the database went away")
        return await real(*args, **kwargs)

    monkeypatch.setattr(store, "queue_ack", fail_once)
    failed = await intake.post(tenant, raise_app_exceptions=False)
    assert failed.status_code == 500
    assert await totals(tenant) == {"Message": 0, "Job": 0, "Contact": 0, "Conversation": 0, "ConsentRecord": 0}
    retried = await intake.post(tenant)
    assert retried.status_code == 200
    assert await totals(tenant) == {"Message": 1, "Job": 1, "Contact": 1, "Conversation": 1, "ConsentRecord": 1}


async def test_the_same_sid_in_two_clinics_is_two_messages(intake, make_tenant):
    a, b = await make_tenant(), await make_tenant()
    await intake.post(a)
    await intake.post(b)
    assert await count(a, Message) == 1 and await count(b, Message) == 1


async def test_a_text_is_stored_with_the_key_that_blocks_a_second_one(intake, make_tenant):
    tenant = await make_tenant()
    await intake.post(tenant, twilio_pairs(Body=BODY))
    (message,) = await rows(tenant, Message)
    assert message.provider_message_id == twilio_pairs()[0][1]
    assert message.idempotency_key == f"in:{message.provider_message_id}"
