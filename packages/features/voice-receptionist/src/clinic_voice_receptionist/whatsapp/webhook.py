"""``/whatsapp/webhook``: Meta calls this when someone writes to a clinic's WhatsApp number.

It runs only in its own Cloud Run service (``service_app.py``). There is no staff session, so a request is trusted
only if its ``X-Hub-Signature-256`` matches the Meta app secret. The clinic and agent come from the number that was
written to. Each message is stored encrypted, answered by the model, and the answer is sent and stored. Meta retries a
webhook it did not get a 200 for, and its message id is stored once, so a retry never answers twice.
"""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import select

from clinic_core.database import system_session, tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_db.models.voice import WhatsAppAccount
from clinic_knowledge.config import get_knowledge_settings
from clinic_knowledge.embeddings import Embedder
from clinic_knowledge.queue import embedder_for
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.knowledge.lookup import run_search
from clinic_voice_receptionist.whatsapp import crypto, service
from clinic_voice_receptionist.whatsapp.graph import GraphError, MetaGraph, WhatsAppGraph
from clinic_voice_receptionist.whatsapp.reply import GeminiReply, ReplyModel, system_instruction

log = logging.getLogger("voice.whatsapp")
FEATURE_KEY = "voice_receptionist"
WEBHOOK_PATH = "/whatsapp/webhook"
MAX_BODY_BYTES = 1_000_000

router = APIRouter(tags=["voice_receptionist"])

FALLBACK_REPLY = "Sorry, something went wrong on our side. Please try again in a few minutes."
NOT_TEXT_REPLY = "Sorry, I can only read text messages for now. Please write your question."


def is_valid_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.get(WEBHOOK_PATH)
async def verify(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Meta's one-time check when the webhook is registered: echo the challenge if the verify token matches."""
    expected = get_voice_settings().whatsapp_verify_token
    if mode == "subscribe" and expected and token and challenge and hmac.compare_digest(token, expected):
        return Response(challenge, media_type="text/plain")
    return Response("Forbidden", status_code=403)


@dataclass
class Incoming:
    phone_number_id: str
    wa_id: str
    name: str | None
    message_id: str
    text: str | None  # None for anything that is not a text message


def parse(payload: dict) -> list[Incoming]:
    found: list[Incoming] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            phone_number_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            names = {c.get("wa_id"): (c.get("profile") or {}).get("name") for c in value.get("contacts") or []}
            for message in value.get("messages") or []:  # delivery "statuses" are not messages and are ignored
                wa_id, message_id = message.get("from"), message.get("id")
                if not (phone_number_id and wa_id and message_id):
                    continue
                text = (message.get("text") or {}).get("body") if message.get("type") == "text" else None
                found.append(Incoming(phone_number_id, str(wa_id), names.get(wa_id), str(message_id), text))
    return found


@router.post(WEBHOOK_PATH)
async def receive(request: Request) -> Response:
    settings = get_voice_settings()
    if not settings.whatsapp_app_secret:
        return Response("WhatsApp is not set up on this server.", status_code=503)
    body = await request.body()
    if len(body) > MAX_BODY_BYTES or not is_valid_signature(
        settings.whatsapp_app_secret, body, request.headers.get("x-hub-signature-256")
    ):
        return Response("Forbidden", status_code=403)  # nothing from the request has been used yet
    try:
        incoming = parse(json.loads(body))
    except (ValueError, AttributeError, TypeError):
        return Response("Bad request", status_code=400)
    graph: WhatsAppGraph = getattr(request.app.state, "whatsapp_graph", None) or MetaGraph()
    model: ReplyModel = getattr(request.app.state, "whatsapp_model", None) or GeminiReply(settings)
    embedder = embedder_for(request.app, get_knowledge_settings())
    for message in incoming:
        try:
            await handle(message, graph=graph, model=model, embedder=embedder)
        except Exception:  # one bad message must not make Meta resend the whole batch; no text or numbers in logs
            log.exception("could not handle a WhatsApp message")
    return Response(status_code=200)


async def handle(
    message: Incoming, *, graph: WhatsAppGraph, model: ReplyModel, embedder: Embedder | None = None
) -> None:
    settings = get_voice_settings()
    # Which clinic owns the number is not known yet, so this one lookup uses the system role.
    async with system_session() as db:
        tenant_id = await db.scalar(
            select(WhatsAppAccount.tenant_id).where(WhatsAppAccount.phone_number_id == message.phone_number_id)
        )
    if tenant_id is None:
        return

    async with tenant_session(tenant_id) as session:
        account = await service.get_account(session)
        if account is None or not account.is_active or FEATURE_KEY not in await enabled_feature_keys(session):
            return
        inbound = await service.record_inbound(
            session,
            account,
            wa_id=message.wa_id,
            name=message.name,
            message_id=message.message_id,
            text=message.text or "[unsupported message type]",
            history=settings.whatsapp_history_messages,
        )
        if inbound is None:
            return  # a retry of a message that was already handled
        if inbound.paused:
            return  # staff took over this chat: the message is saved, and a person will answer it
        token = crypto.decrypt(tenant_id, account.access_token_enc)
        use_knowledge = account.use_knowledge
        system = system_instruction(
            account.prompt, greeting=account.greeting, first_message=inbound.first_message, knowledge=use_knowledge
        )
        phone_number_id = account.phone_number_id
    # The session is closed here: the model and Meta are slow, and no database connection waits on them.

    if message.text is None:
        reply = NOT_TEXT_REPLY
    else:
        search = None
        if use_knowledge:

            async def search(args: dict) -> dict:  # runs in this clinic's own session: the tenant is never an argument
                return await run_search(tenant_id=tenant_id, args=args, embedder=embedder, database_url=None)

        try:
            reply = await model.reply(system, inbound.turns, search=search)
        except Exception:
            log.warning("the WhatsApp agent could not answer", exc_info=True)
            reply = FALLBACK_REPLY

    # Staff may have taken over while the model was writing. Look again, so the agent never talks over a person.
    async with tenant_session(tenant_id) as session:
        if await service.is_paused(session, inbound.conversation_id):
            return
    sent_id: str | None = None
    status = "sent"
    try:
        sent_id = await graph.send_text(phone_number_id, token, message.wa_id, reply)
    except GraphError as exc:
        log.warning("WhatsApp send failed: %s", exc)
        status = "failed"  # kept in the history so staff can see the person was not answered
    async with tenant_session(tenant_id) as session:
        await service.record_outbound(
            session, tenant_id, inbound.conversation_id, text=reply, message_id=sent_id, status=status
        )
