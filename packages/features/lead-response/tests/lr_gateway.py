"""Helpers for the gateway tests: a fake provider, a clock, and a lead with a phone number and a conversation.
Every number and every word here is made up. Nothing in these helpers can reach the network."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from clinic_core.database import system_session, tenant_session
from clinic_db.models.core import Tenant
from clinic_db.models.lead_response import (
    ConsentRecord,
    Contact,
    ContactIdentity,
    Conversation,
    Message,
    MessageEvent,
    PracticeSettings,
)
from clinic_db.models.ops import AuditLog
from clinic_lead_response.gateway.provider import ProviderError, ProviderRequest, ProviderResult
from clinic_lead_response.gateway.retry import ErrorKind
from clinic_lead_response.gateway.service import Gateway
from clinic_lead_response.gateway.types import Lane, Purpose, SendRequest
from clinic_lead_response.settings_model import LeadResponseSettings
from clinic_lead_response.settings_store import columns_from_settings

BODY = "Zebra-Quartz sentinel wording that must never be logged"
PHONE = "+14155550142"
FROM = "+14155550100"
DAYTIME = datetime(2026, 5, 1, 15, 0, tzinfo=UTC)  # 11:00 in New York
NIGHT_UTC = datetime(2026, 5, 2, 3, 4, tzinfo=UTC)  # 23:04 on 1 May in New York (the chart's own example)


def accepted(sid: str = "SM1") -> ProviderResult:
    return ProviderResult(True, provider_message_id=sid, provider_status="queued")


def failure(kind: ErrorKind, code: str | None = "99999", http_status: int | None = 400, retry_after=None):
    return ProviderResult(False, error=ProviderError(kind, code, http_status, retry_after))


class FakeProvider:
    """Answers from a script (the last answer repeats) and remembers every request it was given."""

    name = "fake"

    def __init__(self, *script: ProviderResult, hook=None):
        self.script = list(script) or [accepted()]
        self.requests: list[ProviderRequest] = []
        self.hook = hook  # an async callable run inside send(), to look at the world during the call

    async def send(self, request: ProviderRequest) -> ProviderResult:
        self.requests.append(request)
        if self.hook is not None:
            await self.hook(request)
        return self.script.pop(0) if len(self.script) > 1 else self.script[0]


class RaisingProvider:
    name = "raising"

    async def send(self, request):
        raise RuntimeError("an adapter bug")


class FixedNumber:
    def __init__(self, number: str | None = FROM):
        self.number = number

    async def resolve(self, tenant_id, conversation_id):
        return self.number


class Clock:
    def __init__(self, now: datetime = DAYTIME):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now += timedelta(**kw)


def gateway(provider=None, *, clock=None, number=FROM, **kw) -> Gateway:
    return Gateway(provider or FakeProvider(), FixedNumber(number), clock=clock or Clock(), **kw)


@dataclass(frozen=True)
class Lead:
    tenant: uuid.UUID
    contact: uuid.UUID
    conversation: uuid.UUID


async def make_lead(
    tenant: uuid.UUID,
    *,
    phone: str | None = PHONE,
    consent: tuple[bool, str] | None = None,
    timezone: str | None = None,
) -> Lead:
    """A contact with a phone number (unless ``phone`` is None), an SMS conversation, and maybe one consent record."""
    if timezone is not None:
        async with system_session() as s:
            (await s.get(Tenant, tenant)).timezone = timezone
    async with tenant_session(tenant) as s:
        contact = Contact(tenant_id=tenant)
        s.add(contact)
        await s.flush()
        if phone is not None:
            s.add(ContactIdentity(tenant_id=tenant, contact_id=contact.id, kind="phone", value=phone))
        conversation = Conversation(tenant_id=tenant, contact_id=contact.id, channel="sms", channel_address=FROM)
        s.add(conversation)
        if consent is not None:
            s.add(
                ConsentRecord(
                    tenant_id=tenant,
                    contact_id=contact.id,
                    channel="sms",
                    granted=consent[0],
                    source=consent[1],
                    created_at=DAYTIME - timedelta(days=1),
                )
            )
        await s.flush()
        return Lead(tenant, contact.id, conversation.id)


async def set_settings(tenant: uuid.UUID, **fields) -> None:
    async with tenant_session(tenant) as s:
        s.add(PracticeSettings(tenant_id=tenant, version=1, **columns_from_settings(LeadResponseSettings(**fields))))


def request(lead: Lead, *, purpose=Purpose.ACK, lane=Lane.LIVE, key=None, body=BODY, trace=None) -> SendRequest:
    return SendRequest(
        conversation_id=lead.conversation,
        purpose=purpose,
        body=body,
        lane=lane,
        idempotency_key=key or f"{purpose.value}:{uuid.uuid4()}",
        trace_id=trace or uuid.uuid4(),
    )


async def messages(tenant: uuid.UUID) -> list[Message]:
    async with tenant_session(tenant) as s:
        return list(await s.scalars(select(Message).order_by(Message.created_at, Message.id)))


async def events(tenant: uuid.UUID, message_id: uuid.UUID) -> list[MessageEvent]:
    async with tenant_session(tenant) as s:
        return list(
            await s.scalars(
                select(MessageEvent)
                .where(MessageEvent.message_id == message_id)
                .order_by(MessageEvent.created_at, MessageEvent.attempt)
            )
        )


async def event_pairs(tenant: uuid.UUID, message_id: uuid.UUID) -> list[tuple[int, str]]:
    return [(e.attempt, e.status) for e in await events(tenant, message_id)]


async def consents(tenant: uuid.UUID, contact: uuid.UUID) -> list[ConsentRecord]:
    async with tenant_session(tenant) as s:
        return list(
            await s.scalars(
                select(ConsentRecord)
                .where(ConsentRecord.contact_id == contact)
                .order_by(ConsentRecord.created_at, ConsentRecord.id)
            )
        )


async def audit_rows(tenant: uuid.UUID, action: str) -> list[AuditLog]:
    async with tenant_session(tenant) as s:
        return list(await s.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id)))
