"""The WhatsApp agent for staff: connect the clinic's number, set the agent, and read the chats.

Meta's webhook is not here. It runs as its own service (``service_app.py``), so patient messages never compete with the
clinic's own traffic."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_core.database import tenant_session
from clinic_db.models.core import StaffRole
from clinic_db.models.ops import AuditLog
from clinic_db.models.voice import WhatsAppConversation
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.whatsapp import crypto, service
from clinic_voice_receptionist.whatsapp.graph import GraphError, MetaGraph, WhatsAppGraph
from clinic_voice_receptionist.whatsapp.webhook import WEBHOOK_PATH

log = logging.getLogger("voice.whatsapp")
router = APIRouter(prefix="/inbound/whatsapp", tags=["voice_receptionist"])

# WhatsApp lets a business send free text only within 24 hours of the person's last message. After that, only approved
# template messages work, and those are not built yet.
REPLY_WINDOW = timedelta(hours=24)
# An open chat window asks for new messages every few seconds, so one "viewed" audit line is written per person and
# chat in this time, not one per refresh.
VIEW_AUDIT_EVERY = timedelta(minutes=5)

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]

DEFAULT_PROMPT = (
    "You are the WhatsApp assistant of our clinic. Help people with opening hours, location, services and how to "
    "book an appointment. Be warm and brief."
)


class WhatsAppAccountOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    phone_number_id: str
    display_number: str | None
    agent_name: str
    prompt: str
    greeting: str | None
    is_active: bool
    use_knowledge: bool
    created_at: datetime


class WhatsAppAccountStateOut(BaseModel):
    account: WhatsAppAccountOut | None
    webhook_url: str | None  # what staff paste into Meta's webhook settings
    ready: bool  # false when this server does not know the address of the WhatsApp service yet
    default_prompt: str


class WhatsAppAccountIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone_number_id: str = Field(min_length=1, max_length=64, pattern=r"^\d+$")
    access_token: str | None = Field(
        default=None, min_length=10, max_length=1000, repr=False
    )  # blank keeps the saved one
    agent_name: str = Field(default="WhatsApp assistant", min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=8000)
    greeting: str | None = Field(default=None, max_length=1000)
    is_active: bool = True
    use_knowledge: bool = False


class WhatsAppConversationOut(BaseModel):
    id: uuid.UUID
    contact_number: str
    contact_name: str | None
    last_message_at: datetime
    message_count: int
    last_message: str | None
    last_direction: Literal["inbound", "outbound"] | None
    agent_paused: bool
    paused_at: datetime | None


class WhatsAppMessageOut(BaseModel):
    id: uuid.UUID
    direction: Literal["inbound", "outbound"]
    text: str
    status: str
    created_at: datetime
    from_staff: bool
    sent_by: str | None


class WhatsAppReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=service.MAX_TEXT)


class WhatsAppPauseOut(BaseModel):
    agent_paused: bool
    paused_at: datetime | None


class WhatsAppConversationDetailOut(BaseModel):
    conversation: WhatsAppConversationOut
    messages: list[WhatsAppMessageOut]


def _graph(request: Request) -> WhatsAppGraph:
    return getattr(request.app.state, "whatsapp_graph", None) or MetaGraph()


@router.get("/account", response_model=WhatsAppAccountStateOut, dependencies=MANAGERS)
async def get_account(session: AsyncSession = Depends(get_session)) -> WhatsAppAccountStateOut:
    settings = get_voice_settings()
    base = settings.whatsapp_public_url.strip().rstrip("/")
    account = await service.get_account(session)
    return WhatsAppAccountStateOut(
        account=WhatsAppAccountOut.model_validate(account) if account else None,
        webhook_url=base + WEBHOOK_PATH if base else None,
        ready=bool(base),
        default_prompt=DEFAULT_PROMPT,
    )


@router.put("/account", response_model=WhatsAppAccountOut, dependencies=MANAGERS)
async def save_account(
    body: WhatsAppAccountIn,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> WhatsAppAccountOut:
    existing = await service.get_account(session)
    token = body.access_token
    display = existing.display_number if existing else None
    if token or existing is None or existing.phone_number_id != body.phone_number_id:
        if not token:
            raise HTTPException(422, "Add the access token from Meta to connect this number.")
        try:  # a token Meta rejects must not be saved, or the agent would stay silent with no warning
            display = await _graph(request).display_number(body.phone_number_id, token)
        except GraphError as exc:
            raise HTTPException(exc.status, str(exc)) from None
    try:
        account = await service.save_account(
            session,
            ctx.tenant_id,
            phone_number_id=body.phone_number_id,
            access_token=token,
            display_number=display,
            agent_name=body.agent_name.strip(),
            prompt=body.prompt.strip(),
            greeting=(body.greeting or "").strip() or None,
            is_active=body.is_active,
            use_knowledge=body.use_knowledge,
        )
        await audit(
            session,
            "voice.whatsapp.account_saved",
            actor_type="staff",
            actor_id=ctx.actor_id,
            entity_type="voice.whatsapp_account",
            entity_id=account.id,
        )
    except service.AccountError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except IntegrityError:
        raise HTTPException(409, "That WhatsApp number is already connected to another clinic.") from None
    return WhatsAppAccountOut.model_validate(account)


@router.delete("/account", status_code=204, dependencies=MANAGERS)
async def disconnect_account(
    ctx: RequestContext = Depends(get_request_context), session: AsyncSession = Depends(get_session)
) -> None:
    account = await service.delete_account(session)
    if account is None:
        raise HTTPException(404, "No WhatsApp number is connected.")
    await audit(
        session,
        "voice.whatsapp.account_removed",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.whatsapp_account",
        entity_id=account.id,
    )


@router.get("/conversations", response_model=list[WhatsAppConversationOut])
async def list_conversations(
    ctx: RequestContext = Depends(get_request_context), session: AsyncSession = Depends(get_session)
) -> list[WhatsAppConversationOut]:
    rows = await service.list_conversations(session, ctx.tenant_id)
    return [WhatsAppConversationOut(**vars(row)) for row in rows]


@router.get("/conversations/{conversation_id}", response_model=WhatsAppConversationDetailOut)
async def read_conversation(
    conversation_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> WhatsAppConversationDetailOut:
    found = await service.get_conversation(session, ctx.tenant_id, conversation_id)
    if found is None:
        raise HTTPException(404, "That conversation no longer exists.")
    conversation, messages = found
    recently = await session.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.action == "voice.whatsapp.conversation_viewed",
            AuditLog.actor_id == ctx.actor_id,
            AuditLog.entity_id == conversation_id,
            AuditLog.occurred_at > datetime.now(UTC) - VIEW_AUDIT_EVERY,
        )
        .limit(1)
    )
    if recently is None:  # patient messages are PHI: opening a chat is recorded
        await audit(
            session,
            "voice.whatsapp.conversation_viewed",
            actor_type="staff",
            actor_id=ctx.actor_id,
            entity_type="voice.whatsapp_conversation",
            entity_id=conversation_id,
        )
    return WhatsAppConversationDetailOut(
        conversation=WhatsAppConversationOut(**vars(conversation)),
        messages=[WhatsAppMessageOut(**vars(m)) for m in messages],
    )


def _staff_id(ctx: RequestContext) -> uuid.UUID | None:
    try:
        return uuid.UUID(ctx.actor_id)
    except ValueError:
        return None  # dev-only sign-in without a staff row


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=WhatsAppMessageOut,
    status_code=201,
    dependencies=MANAGERS,
)
async def send_reply(
    conversation_id: uuid.UUID,
    body: WhatsAppReplyIn,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> WhatsAppMessageOut:
    """A staff member answers the person. The agent is paused for this chat first, so it never talks over the person."""
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Write a message first.")
    conversation = await session.get(WhatsAppConversation, conversation_id)
    if conversation is None:
        raise HTTPException(404, "That conversation no longer exists.")
    account = await service.get_account(session)
    if account is None:
        raise HTTPException(409, "No WhatsApp number is connected.")
    last = await service.last_patient_message_at(session, conversation_id)
    if last is None or datetime.now(UTC) - last > REPLY_WINDOW:
        raise HTTPException(
            409,
            "The 24-hour reply window is closed. WhatsApp allows a free message only within 24 hours of the "
            "person's last message.",
        )
    staff_id = _staff_id(ctx)
    # Pause in its own committed transaction, before anything is sent, so a patient message that arrives now is not
    # answered by the agent while this reply is on its way.
    async with tenant_session(ctx.tenant_id, database_url=ctx.database_url) as pause_session:
        await service.set_paused(pause_session, conversation_id, True, staff_id)
    sent_id: str | None = None
    status = "sent"
    try:
        sent_id = await _graph(request).send_text(
            account.phone_number_id,
            crypto.decrypt(ctx.tenant_id, account.access_token_enc),
            crypto.decrypt(ctx.tenant_id, conversation.contact_number_enc),
            text,
        )
    except GraphError as exc:
        log.warning("WhatsApp staff reply was not delivered: %s", exc)  # no text or numbers in logs
        status = "failed"  # kept in the chat, marked not delivered, so the person who wrote it can see
    message = await service.record_outbound(
        session, ctx.tenant_id, conversation_id, text=text, message_id=sent_id, status=status, staff_id=staff_id
    )
    await audit(  # who wrote to a patient is recorded; the text is not
        session,
        "voice.whatsapp.staff_reply",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.whatsapp_conversation",
        entity_id=conversation_id,
        details={"status": status},
    )
    names = await service.staff_names(session, {staff_id} if staff_id else set())
    return WhatsAppMessageOut(
        id=message.id,
        direction="outbound",
        text=text,
        status=status,
        created_at=message.created_at,
        from_staff=staff_id is not None,
        sent_by=names.get(staff_id) if staff_id else None,
    )


async def _set_paused(conversation_id: uuid.UUID, paused: bool, ctx: RequestContext, session: AsyncSession):
    conversation = await service.set_paused(session, conversation_id, paused, _staff_id(ctx))
    if conversation is None:
        raise HTTPException(404, "That conversation no longer exists.")
    await audit(
        session,
        "voice.whatsapp.agent_paused" if paused else "voice.whatsapp.agent_resumed",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="voice.whatsapp_conversation",
        entity_id=conversation_id,
    )
    return WhatsAppPauseOut(agent_paused=conversation.agent_paused, paused_at=conversation.paused_at)


@router.post("/conversations/{conversation_id}/pause", response_model=WhatsAppPauseOut, dependencies=MANAGERS)
async def pause_agent(
    conversation_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> WhatsAppPauseOut:
    return await _set_paused(conversation_id, True, ctx, session)


@router.post("/conversations/{conversation_id}/resume", response_model=WhatsAppPauseOut, dependencies=MANAGERS)
async def resume_agent(
    conversation_id: uuid.UUID,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> WhatsAppPauseOut:
    return await _set_paused(conversation_id, False, ctx, session)
