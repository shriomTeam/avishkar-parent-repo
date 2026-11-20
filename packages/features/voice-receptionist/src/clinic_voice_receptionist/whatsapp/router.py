"""The WhatsApp agent for staff: connect the clinic's number, set the agent, and read the chats.

Meta's webhook is not here. It runs as its own service (``service_app.py``), so patient messages never compete with the
clinic's own traffic."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_db.models.core import StaffRole
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.whatsapp import service
from clinic_voice_receptionist.whatsapp.graph import GraphError, MetaGraph, WhatsAppGraph
from clinic_voice_receptionist.whatsapp.webhook import WEBHOOK_PATH

router = APIRouter(prefix="/inbound/whatsapp", tags=["voice_receptionist"])

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


class WhatsAppMessageOut(BaseModel):
    id: uuid.UUID
    direction: Literal["inbound", "outbound"]
    text: str
    status: str
    created_at: datetime


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
    await audit(  # patient messages are PHI: every read is recorded
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
