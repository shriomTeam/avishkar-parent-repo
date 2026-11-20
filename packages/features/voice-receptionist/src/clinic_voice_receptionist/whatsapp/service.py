"""A clinic's WhatsApp account and chats. Runs inside a tenant session. Text is encrypted here, before it is stored."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.voice import WhatsAppAccount, WhatsAppConversation, WhatsAppMessage
from clinic_voice_receptionist.whatsapp import crypto
from clinic_voice_receptionist.whatsapp.reply import Turn

MAX_TEXT = 4096  # WhatsApp's own limit for a text message


class AccountError(Exception):
    """A problem staff can fix; the message is shown as written."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


async def get_account(session: AsyncSession) -> WhatsAppAccount | None:
    return await session.scalar(select(WhatsAppAccount))


async def save_account(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    phone_number_id: str,
    access_token: str | None,
    display_number: str | None,
    agent_name: str,
    prompt: str,
    greeting: str | None,
    is_active: bool,
    use_knowledge: bool,
) -> WhatsAppAccount:
    account = await get_account(session)
    taken = await session.scalar(
        select(WhatsAppAccount.id).where(
            WhatsAppAccount.phone_number_id == phone_number_id, WhatsAppAccount.tenant_id != tenant_id
        )
    )
    if taken is not None:
        raise AccountError("That WhatsApp number is already connected to another clinic.")
    if account is None:
        if not access_token:
            raise AccountError("Add the access token from Meta to connect the number.", 422)
        account = WhatsAppAccount(tenant_id=tenant_id, access_token_enc="")
        session.add(account)
    account.phone_number_id = phone_number_id
    account.display_number = display_number
    if access_token:
        account.access_token_enc = crypto.encrypt(tenant_id, access_token)
    account.agent_name = agent_name
    account.prompt = prompt
    account.greeting = greeting
    account.is_active = is_active
    account.use_knowledge = use_knowledge
    await session.flush()
    return account


async def delete_account(session: AsyncSession) -> WhatsAppAccount | None:
    account = await get_account(session)
    if account is not None:
        await session.delete(account)  # chats and messages go with it (ON DELETE CASCADE)
        await session.flush()
    return account


@dataclass
class Inbound:
    conversation_id: uuid.UUID
    first_message: bool
    turns: list[Turn]  # recent chat including the new message, oldest first


async def record_inbound(
    session: AsyncSession,
    account: WhatsAppAccount,
    *,
    wa_id: str,
    name: str | None,
    message_id: str,
    text: str,
    history: int,
) -> Inbound | None:
    """Store a message from a person. Returns None when this message id was already stored (Meta retried)."""
    tenant_id = account.tenant_id
    now = datetime.now(UTC)
    digest = crypto.contact_hash(tenant_id, wa_id)
    # Two first messages at once must end in one chat, so insert and ignore a conflict, then read the row.
    await session.execute(
        insert(WhatsAppConversation)
        .values(
            tenant_id=tenant_id,
            account_id=account.id,
            contact_hash=digest,
            contact_number_enc=crypto.encrypt(tenant_id, wa_id),
            contact_name_enc=crypto.encrypt(tenant_id, name) if name else None,
            last_message_at=now,
        )
        .on_conflict_do_nothing(index_elements=["account_id", "contact_hash"])
    )
    conversation = await session.scalar(
        select(WhatsAppConversation).where(
            WhatsAppConversation.account_id == account.id, WhatsAppConversation.contact_hash == digest
        )
    )
    stored = await session.scalar(
        insert(WhatsAppMessage)
        .values(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            provider_message_id=message_id,
            body_enc=crypto.encrypt(tenant_id, text[:MAX_TEXT]),
            status="received",
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "provider_message_id"])
        .returning(WhatsAppMessage.id)
    )
    if stored is None:
        return None
    first = conversation.message_count == 0
    conversation.message_count += 1
    conversation.last_message_at = now
    if name and conversation.contact_name_enc is None:
        conversation.contact_name_enc = crypto.encrypt(tenant_id, name)
    await session.flush()
    return Inbound(conversation.id, first, await recent_turns(session, tenant_id, conversation.id, history))


async def record_outbound(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    *,
    text: str,
    message_id: str | None,
    status: str,
) -> None:
    now = datetime.now(UTC)
    session.add(
        WhatsAppMessage(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            direction="outbound",
            provider_message_id=message_id,
            body_enc=crypto.encrypt(tenant_id, text[:MAX_TEXT]),
            status=status,
            created_at=now,
        )
    )
    conversation = await session.get(WhatsAppConversation, conversation_id)
    conversation.message_count += 1
    conversation.last_message_at = now
    await session.flush()


async def recent_turns(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID, limit: int
) -> list[Turn]:
    rows = (
        await session.execute(
            select(WhatsAppMessage.direction, WhatsAppMessage.body_enc, WhatsAppMessage.status)
            .where(WhatsAppMessage.conversation_id == conversation_id)
            .order_by(WhatsAppMessage.created_at.desc(), WhatsAppMessage.id.desc())
            .limit(limit)
        )
    ).all()
    # A reply that failed to send was never seen by the person, so the model must not treat it as said.
    return [
        ("user" if direction == "inbound" else "model", crypto.decrypt(tenant_id, body))
        for direction, body, status in reversed(rows)
        if status != "failed"
    ]


@dataclass
class ConversationView:
    id: uuid.UUID
    contact_number: str
    contact_name: str | None
    last_message_at: datetime
    message_count: int
    last_message: str | None
    last_direction: str | None


async def list_conversations(session: AsyncSession, tenant_id: uuid.UUID, limit: int = 100) -> list[ConversationView]:
    conversations = (
        await session.scalars(
            select(WhatsAppConversation).order_by(WhatsAppConversation.last_message_at.desc()).limit(limit)
        )
    ).all()
    # The newest message of each chat, in one query.
    newest = (
        select(WhatsAppMessage.conversation_id, func.max(WhatsAppMessage.created_at).label("at"))
        .where(WhatsAppMessage.conversation_id.in_([c.id for c in conversations]))
        .group_by(WhatsAppMessage.conversation_id)
        .subquery()
    )
    last = {
        row.conversation_id: row
        for row in (
            await session.execute(
                select(WhatsAppMessage.conversation_id, WhatsAppMessage.body_enc, WhatsAppMessage.direction).join(
                    newest,
                    (WhatsAppMessage.conversation_id == newest.c.conversation_id)
                    & (WhatsAppMessage.created_at == newest.c.at),
                )
            )
        ).all()
    }
    return [
        ConversationView(
            id=c.id,
            contact_number=crypto.decrypt(tenant_id, c.contact_number_enc),
            contact_name=crypto.decrypt(tenant_id, c.contact_name_enc) if c.contact_name_enc else None,
            last_message_at=c.last_message_at,
            message_count=c.message_count,
            last_message=crypto.decrypt(tenant_id, last[c.id].body_enc)[:160] if c.id in last else None,
            last_direction=last[c.id].direction if c.id in last else None,
        )
        for c in conversations
    ]


@dataclass
class MessageView:
    id: uuid.UUID
    direction: str
    text: str
    status: str
    created_at: datetime


async def get_conversation(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[ConversationView, list[MessageView]] | None:
    conversation = await session.get(WhatsAppConversation, conversation_id)
    if conversation is None:
        return None
    rows = (
        await session.scalars(
            select(WhatsAppMessage)
            .where(WhatsAppMessage.conversation_id == conversation_id)
            .order_by(WhatsAppMessage.created_at, WhatsAppMessage.id)
        )
    ).all()
    messages = [
        MessageView(m.id, m.direction, crypto.decrypt(tenant_id, m.body_enc), m.status, m.created_at) for m in rows
    ]
    view = ConversationView(
        id=conversation.id,
        contact_number=crypto.decrypt(tenant_id, conversation.contact_number_enc),
        contact_name=crypto.decrypt(tenant_id, conversation.contact_name_enc)
        if conversation.contact_name_enc
        else None,
        last_message_at=conversation.last_message_at,
        message_count=conversation.message_count,
        last_message=messages[-1].text[:160] if messages else None,
        last_direction=messages[-1].direction if messages else None,
    )
    return view, messages
