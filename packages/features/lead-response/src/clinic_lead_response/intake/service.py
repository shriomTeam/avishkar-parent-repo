"""Taking one verified inbound text into the system, in ONE transaction that commits before the route answers.

Nothing here calls a provider or the network: the ack is a durable job row, written with the message, that a later chunk
sends. Everything runs in the tenant's session, so row-level security applies to every read and write.

Statements for an ordinary text from a known lead: set_config, feature check, contact lookup, conversation upsert,
message insert, first-inbound consent, flood count, ack job (8). A new lead adds the contact and identity inserts and
their savepoint. A retry of a stored message stops after the message insert.
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
    throttled: bool = False  # saved, but too many texts too fast for us to answer each one


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
        message_id = await store.insert_inbound(
            session, conversation_id=conversation_id, sid=text.message_sid, body=text.body, trace_id=trace_id
        )
        if message_id is None:
            return Accepted(Outcome.DUPLICATE, conversation_id=conversation_id, contact_id=contact_id)
        await store.record_first_inbound_consent(
            session, contact_id=contact_id, message_id=message_id, trace_id=trace_id
        )
        throttled = await store.recent_inbound_count(session, conversation_id) > MAX_PER_MINUTE
        ack_queued = False
        if not throttled:
            ack_queued = await store.queue_ack(
                session, conversation_id=conversation_id, message_id=message_id, trace_id=trace_id, now=now
            )
    return Accepted(
        Outcome.STORED,
        message_id=message_id,
        conversation_id=conversation_id,
        contact_id=contact_id,
        new_contact=new_contact,
        ack_queued=ack_queued,
        throttled=throttled,
    )
