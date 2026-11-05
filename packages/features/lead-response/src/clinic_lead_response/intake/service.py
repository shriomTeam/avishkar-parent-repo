"""Taking one verified inbound text into the system, in ONE transaction that commits before the route answers.

Nothing here calls a provider or the network: the ack is a durable job row, written with the message, that a later chunk
sends. Everything runs in the tenant's session, so row-level security applies to every read and write.

Statements for an ordinary text from a known lead: set_config, feature check, contact lookup, conversation upsert,
message insert, first-inbound consent, flood count, ack job (8). A new lead adds the contact and identity inserts and
their savepoint. A retry of a stored message stops after the message insert.

STOP, START and HELP are told apart here, in the same transaction, but acted on afterwards (``apply_keyword``), in a
second transaction of their own: the gateway owns consent. A keyword text gets no ack. STOP and START get no job at all
and no first-inbound grant; HELP gets a ``help`` job instead of an ack.
"""

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_lead_response.gateway.keywords import Keyword, classify_inbound
from clinic_lead_response.gateway.service import Gateway
from clinic_lead_response.intake import store
from clinic_lead_response.intake.parse import InboundText

FEATURE_KEY = "lead_response"
MAX_PER_MINUTE = 20  # more inbound texts than this in one conversation in a minute are kept but get no ack


class Outcome(StrEnum):
    STORED = "stored"
    DUPLICATE = "duplicate"  # a Twilio retry of a text we already have
    NOT_ENABLED = "not_enabled"  # no such clinic, or it does not have the feature: nothing was written


@dataclass(frozen=True)
class Accepted:
    outcome: Outcome
    message_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    new_contact: bool = False
    ack_queued: bool = False
    help_queued: bool = False
    throttled: bool = False  # saved, but too many texts too fast for us to answer each one
    keyword: Keyword | None = None  # what the text meant to the carriers, if anything
    keyword_pending: bool = False  # the keyword still has to be applied (new, or a retry whose effect is missing)
    tenant_id: uuid.UUID | None = None  # who it belongs to and the trace it carries, for the hook after the commit
    trace_id: uuid.UUID | None = None


SessionScope = Callable[[uuid.UUID], AbstractAsyncContextManager[AsyncSession]]


async def accept(
    tenant_id: uuid.UUID,
    text: InboundText,
    *,
    trace_id: uuid.UUID,
    now: datetime | None = None,
    session_scope: SessionScope | None = None,
) -> Accepted:
    now = now or datetime.now(UTC)
    async with (session_scope or tenant_session)(tenant_id) as session:
        if FEATURE_KEY not in await enabled_feature_keys(session):
            return Accepted(Outcome.NOT_ENABLED)
        contact_id, new_contact = await store.resolve_contact(session, text.sender)
        conversation_id = await store.open_conversation(session, contact_id, text.recipient, now)
        keyword = classify_inbound(text.body)
        message_id = await store.insert_inbound(
            session, conversation_id=conversation_id, sid=text.message_sid, body=text.body, trace_id=trace_id
        )
        if message_id is None:
            return await _repeat(session, text, contact_id, conversation_id, keyword)
        if keyword in (Keyword.STOP, Keyword.START):
            # The gateway records the revocation or grant. No first-inbound grant, no flood count, no job.
            return Accepted(
                Outcome.STORED,
                message_id=message_id,
                conversation_id=conversation_id,
                contact_id=contact_id,
                new_contact=new_contact,
                keyword=keyword,
                keyword_pending=True,
            )
        await store.record_first_inbound_consent(
            session, contact_id=contact_id, message_id=message_id, trace_id=trace_id
        )
        throttled = await store.recent_inbound_count(session, conversation_id) > MAX_PER_MINUTE
        queued = False
        if not throttled:
            queue = store.queue_help if keyword is Keyword.HELP else store.queue_ack
            queued = await queue(
                session, conversation_id=conversation_id, message_id=message_id, trace_id=trace_id, now=now
            )
        ack_queued = queued and keyword is None
        help_queued = queued and keyword is Keyword.HELP
    return Accepted(
        Outcome.STORED,
        message_id=message_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        new_contact=new_contact,
        ack_queued=ack_queued,
        help_queued=help_queued,
        throttled=throttled,
        keyword=keyword,
        keyword_pending=keyword is not None,
        tenant_id=tenant_id,
        trace_id=trace_id,
    )


async def _repeat(
    session: AsyncSession,
    text: InboundText,
    contact_id: uuid.UUID,
    conversation_id: uuid.UUID,
    keyword: Keyword | None,
) -> Accepted:
    """A Twilio retry of a text we already have. If it is a keyword whose effect never happened (the first attempt
    failed after storing it), it must run now: that is what makes a 500 recoverable."""
    pending, message_id = False, None
    if keyword is not None:
        message_id = await store.message_id_for_sid(session, text.message_sid)
        pending = message_id is not None and not await store.keyword_already_applied(session, contact_id, message_id)
    return Accepted(
        Outcome.DUPLICATE,
        message_id=message_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        keyword=keyword,
        keyword_pending=pending,
    )


async def apply_keyword(
    gateway: Gateway, tenant_id: uuid.UUID, accepted: Accepted, text: InboundText, *, trace_id: uuid.UUID
) -> None:
    """STOP revokes, START grants, HELP changes nothing. A second transaction, run after the text is committed; the
    route does not answer until it has finished. Safe to run twice: the gateway records nothing new for a contact who
    is already in that state."""
    if not accepted.keyword_pending or accepted.contact_id is None:
        return
    await gateway.handle_inbound_keyword(
        tenant_id,
        contact_id=accepted.contact_id,
        text=text.body,
        inbound_message_id=accepted.message_id,
        trace_id=trace_id,
    )
