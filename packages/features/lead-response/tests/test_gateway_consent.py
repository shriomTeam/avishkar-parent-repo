"""STOP, START and HELP, and what they do to later sends."""

import uuid
from datetime import UTC, datetime

import pytest
from lr_gateway import (
    DAYTIME,
    FakeProvider,
    audit_rows,
    consents,
    gateway,
    make_lead,
    request,
)

from clinic_core.database import system_session, tenant_session
from clinic_db.models.core import Tenant
from clinic_db.models.lead_response import ConsentRecord
from clinic_lead_response.gateway.keywords import Keyword
from clinic_lead_response.gateway.service import ContactNotFound
from clinic_lead_response.gateway.texts import help_text
from clinic_lead_response.gateway.types import Lane, Outcome, Purpose


async def keyword(t, lead, text, message_id=None):
    return await gateway().handle_inbound_keyword(
        t, contact_id=lead.contact, text=text, inbound_message_id=message_id, trace_id=uuid.uuid4()
    )


async def test_stop_appends_a_revocation_and_audits_it_with_names_only(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "first_inbound"))
    result = await keyword(t, lead, "STOP")
    assert (result.keyword, result.consent_changed, result.reply_text) == (Keyword.STOP, True, None)
    newest = (await consents(t, lead.contact))[-1]
    assert (newest.granted, newest.source, newest.channel) == (False, "stop", "sms")
    (audit,) = await audit_rows(t, "lead_response.consent.changed")
    assert audit.details == {"channel": "sms", "granted": False, "source": "stop"} and audit.entity_id == newest.id


async def test_the_inbound_message_is_linked_to_the_consent_record(make_tenant):
    from clinic_core.database import tenant_session as scope
    from clinic_db.models.lead_response import Message

    t = await make_tenant()
    lead = await make_lead(t)
    async with scope(t) as s:
        inbound = Message(
            tenant_id=t,
            conversation_id=lead.conversation,
            direction="inbound",
            channel="sms",
            sender_kind="contact",
            body="STOP",
        )
        s.add(inbound)
        await s.flush()
        inbound_id = inbound.id
    await keyword(t, lead, "stop", message_id=inbound_id)
    assert (await consents(t, lead.contact))[-1].message_id == inbound_id


@pytest.mark.parametrize(
    "text", ["stop", "  Stop  ", "STOPALL", "unsubscribe", "quit", "cancel", "end", "optout", "revoke"]
)
async def test_every_stop_word_revokes(make_tenant, text):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"))
    assert (await keyword(t, lead, text)).consent_changed
    assert (await consents(t, lead.contact))[-1].granted is False


async def test_a_second_stop_adds_nothing(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    assert (await keyword(t, lead, "STOP")).consent_changed
    assert not (await keyword(t, lead, "STOP")).consent_changed
    assert len(await consents(t, lead.contact)) == 1 and len(await audit_rows(t, "lead_response.consent.changed")) == 1


async def test_start_after_stop_grants_again_with_an_explicit_source(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(False, "stop"))
    result = await keyword(t, lead, "START")
    assert (result.keyword, result.consent_changed) == (Keyword.START, True)
    newest = (await consents(t, lead.contact))[-1]
    assert (newest.granted, newest.source) == (True, "start")


@pytest.mark.parametrize("text", ["start", "UNSTOP", "Yes"])
async def test_every_start_word_grants(make_tenant, text):
    t = await make_tenant()
    lead = await make_lead(t, consent=(False, "stop"))
    assert (await keyword(t, lead, text)).consent_changed


async def test_start_upgrades_a_grant_that_only_came_from_the_first_text(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "first_inbound"))
    assert (await keyword(t, lead, "START")).consent_changed
    assert not (await keyword(t, lead, "START")).consent_changed  # and now it is already explicit


async def test_help_returns_the_text_naming_the_practice_and_changes_no_consent(make_tenant):
    t = await make_tenant()
    async with system_session() as s:
        (await s.get(Tenant, t)).name = "Glow Aesthetics"
    lead = await make_lead(t, consent=(True, "first_inbound"))
    result = await keyword(t, lead, "help")
    assert (result.keyword, result.consent_changed, result.reply_text) == (
        Keyword.HELP,
        False,
        help_text("Glow Aesthetics"),
    )
    assert "Glow Aesthetics" in result.reply_text and "STOP" in result.reply_text
    assert len(await consents(t, lead.contact)) == 1


async def test_an_opted_out_contact_gets_no_help_reply(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(False, "stop"))
    result = await keyword(t, lead, "HELP")
    assert result.keyword is Keyword.HELP and result.reply_text is None


def test_the_help_text_has_a_fallback_name():
    assert help_text("   ").startswith("Our practice")


@pytest.mark.parametrize("text", ["hello", "please stop", "stop.", "I need help", "yes please", ""])
async def test_ordinary_messages_change_nothing(make_tenant, text):
    t = await make_tenant()
    lead = await make_lead(t)
    result = await keyword(t, lead, text)
    assert (result.keyword, result.consent_changed, result.reply_text) == (None, False, None)
    assert await consents(t, lead.contact) == []


async def test_after_stop_a_follow_up_is_blocked_and_after_start_it_goes_out(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "start"))
    g = gateway(FakeProvider())
    await keyword(t, lead, "STOP")
    blocked = await g.send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    await keyword(t, lead, "START")
    sent = await g.send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    assert (blocked.outcome, blocked.reason) == (Outcome.BLOCKED, "opted_out")
    assert sent.outcome is Outcome.SENT


async def test_a_first_text_then_start_is_what_allows_a_follow_up(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t, consent=(True, "first_inbound"))
    g = gateway(FakeProvider())
    before = await g.send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    await keyword(t, lead, "yes")
    after = await g.send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    assert (before.reason, after.outcome) == ("no_consent", Outcome.SENT)


async def test_a_grant_and_a_revocation_with_the_same_timestamp_resolve_to_no_texting(make_tenant):
    t = await make_tenant()
    lead = await make_lead(t)
    stamp = datetime(2026, 4, 30, 12, 0, tzinfo=UTC)
    async with tenant_session(t) as s:
        for granted, source in ((True, "start"), (False, "stop")):
            s.add(
                ConsentRecord(
                    tenant_id=t,
                    contact_id=lead.contact,
                    channel="sms",
                    granted=granted,
                    source=source,
                    created_at=stamp,
                )
            )
    result = await gateway(FakeProvider()).send(t, request(lead, purpose=Purpose.FOLLOW_UP, lane=Lane.FOLLOW_UP))
    assert (result.outcome, result.reason) == (Outcome.BLOCKED, "opted_out")


async def test_a_contact_of_another_tenant_cannot_be_changed(make_tenant):
    a, b = await make_tenant(), await make_tenant()
    lead_a = await make_lead(a)
    with pytest.raises(ContactNotFound):
        await gateway().handle_inbound_keyword(
            b, contact_id=lead_a.contact, text="STOP", inbound_message_id=None, trace_id=uuid.uuid4()
        )
    assert await consents(a, lead_a.contact) == []
    assert DAYTIME  # the helper module is shared; nothing else to check here
