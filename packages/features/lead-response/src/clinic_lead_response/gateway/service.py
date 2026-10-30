"""The gateway: decide, send once, record what happened.

The send is done in three short steps so that no database transaction is open during the HTTP call:
  1. one transaction decides (consent, quiet hours), records the message and a ``sending`` event, and commits;
  2. the provider is called, outside any transaction;
  3. a second transaction records ``sent`` or ``failed``.
A crash between 2 and 3 leaves the message ``sending``. That is indistinguishable from a crash before the call, so it is
never resent: a delivery receipt resolves it, and ``expire_stuck`` surfaces it to staff if none comes. The provider call
is at-most-once from our side per attempt (Twilio documents no idempotency for its Messages API).

``send`` does not raise for provider or policy outcomes; it returns a ``SendResult``. Only programmer errors (a bad
request, a conversation that does not exist for this tenant) and database failures raise.
"""

import logging
import time as clock_time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit
from clinic_core.database import tenant_session
from clinic_lead_response.gateway import store
from clinic_lead_response.gateway.keywords import Keyword, classify_inbound
from clinic_lead_response.gateway.log import log_event, mask_phone
from clinic_lead_response.gateway.policy import FIRST_INBOUND, Block, Defer, current_consent, decide
from clinic_lead_response.gateway.provider import (
    NumberResolver,
    ProviderError,
    ProviderRequest,
    ProviderResult,
    SmsProvider,
)
from clinic_lead_response.gateway.retry import (
    ErrorKind,
    classify_error,
    is_stuck,
    may_resend,
    next_retry,
)
from clinic_lead_response.gateway.status import current_status, map_provider_status
from clinic_lead_response.gateway.texts import help_text
from clinic_lead_response.gateway.types import (
    REPLY_PURPOSES,
    SENDER_KIND,
    BlockReason,
    FailReason,
    KeywordResult,
    Lane,
    MessageStatus,
    Outcome,
    Purpose,
    ReceiptResult,
    SendRequest,
    SendResult,
)
from clinic_lead_response.settings_store import current_settings

log = logging.getLogger("lead_response.gateway")

SessionScope = Callable[[uuid.UUID], AbstractAsyncContextManager[AsyncSession]]
StatusCallbackUrl = Callable[[uuid.UUID, uuid.UUID], str | None]  # (tenant_id, message_id) -> the receipt URL
MAX_KEY_LENGTH = 100  # messages.idempotency_key is a String(100)
CHANNEL = "sms"


class ConversationNotFound(LookupError):
    """No such conversation for this tenant: a caller bug, not an outcome."""


class ContactNotFound(LookupError):
    """No such contact for this tenant: a caller bug, not an outcome."""


class MessageNotFound(LookupError):
    """No such message for this tenant: a caller bug, not an outcome."""


@dataclass(frozen=True)
class _Prepared:
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    contact_id: uuid.UUID
    channel: str
    attempt: int
    to: str
    from_number: str
    body: str
    trace_id: uuid.UUID
    purpose: Purpose


def _validate(request: SendRequest) -> None:
    if not request.body.strip():
        raise ValueError("a message needs a body")
    if not 0 < len(request.idempotency_key) <= MAX_KEY_LENGTH:
        raise ValueError(f"the idempotency key must be 1 to {MAX_KEY_LENGTH} characters")
    Purpose(request.purpose)
    Lane(request.lane)


def _zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


class Gateway:
    def __init__(
        self,
        provider: SmsProvider,
        numbers: NumberResolver,
        *,
        clock: Callable[[], datetime] | None = None,
        session_scope: SessionScope | None = None,
        status_callback: StatusCallbackUrl | None = None,
    ):
        self._provider = provider
        self._numbers = numbers
        self._now = clock or (lambda: datetime.now(UTC))
        self._scope = session_scope or tenant_session
        self._status_callback = status_callback

    # --- sending ------------------------------------------------------------------------------------------------

    async def send(self, tenant_id: uuid.UUID, request: SendRequest) -> SendResult:
        _validate(request)
        prepared = await self._prepare(tenant_id, request)
        if isinstance(prepared, SendResult):
            self._log(tenant_id, request.trace_id, request.lane, request.purpose, prepared)
            return prepared
        result = await self._attempt(tenant_id, prepared, request.lane)
        self._log(tenant_id, request.trace_id, request.lane, request.purpose, result, to=prepared.to)
        return result

    async def _prepare(self, tenant_id: uuid.UUID, request: SendRequest) -> "_Prepared | SendResult":
        async with self._scope(tenant_id) as session:
            existing = await store.find_message_by_key(session, request.idempotency_key)
            if existing is not None:
                return await self._duplicate(session, existing.id)
            ctx = await store.load_send_context(session, request.conversation_id)
            if ctx is None:
                raise ConversationNotFound(str(request.conversation_id))

            if ctx.phone is None:
                return await self._record_stop(
                    session, request, ctx.channel, BlockReason.NO_PHONE, Outcome.BLOCKED, MessageStatus.BLOCKED
                )
            decision = await self._policy(session, request, ctx.contact_id, ctx.channel)
            if isinstance(decision, Defer):
                return SendResult(Outcome.DEFERRED, until=decision.until, reason="quiet_hours")
            if isinstance(decision, Block):
                return await self._record_stop(
                    session, request, ctx.channel, decision.reason, Outcome.BLOCKED, MessageStatus.BLOCKED
                )
            from_number = await self._numbers.resolve(tenant_id, request.conversation_id)
            if from_number is None:
                return await self._record_stop(
                    session, request, ctx.channel, FailReason.NO_FROM_NUMBER, Outcome.FAILED, MessageStatus.FAILED
                )
            message_id = await store.insert_message(
                session,
                conversation_id=request.conversation_id,
                channel=ctx.channel,
                sender_kind=SENDER_KIND[request.purpose],
                body=request.body,
                provider=self._provider.name,
                idempotency_key=request.idempotency_key,
                trace_id=request.trace_id,
                staff_id=request.staff_id,
            )
            if message_id is None:  # another request used this key between our check and our insert
                existing = await store.find_message_by_key(session, request.idempotency_key)
                return await self._duplicate(session, existing.id)
            await store.append_event(
                session, message_id=message_id, attempt=1, status=MessageStatus.SENDING, trace_id=request.trace_id
            )
            return _Prepared(
                message_id,
                request.conversation_id,
                ctx.contact_id,
                ctx.channel,
                1,
                ctx.phone,
                from_number,
                request.body,
                request.trace_id,
                request.purpose,
            )

    async def _policy(self, session: AsyncSession, request: SendRequest, contact_id: uuid.UUID, channel: str):
        tz_name, _name = await store.tenant_info(session)
        _version, settings = await current_settings(session)
        consent = current_consent(await store.consent_snapshots(session, contact_id, channel))
        tz = _zone(tz_name)
        if tz is None:
            if request.purpose not in REPLY_PURPOSES or request.lane is Lane.BULK:
                return Block(BlockReason.BAD_TIMEZONE)
            tz = ZoneInfo("UTC")  # a reply ignores quiet hours, so the zone cannot matter
        return decide(
            purpose=request.purpose,
            lane=request.lane,
            now=self._now(),
            tz=tz,
            quiet_hours=settings.quiet_hours,
            consent=consent,
        )

    async def _record_stop(
        self,
        session: AsyncSession,
        request: SendRequest,
        channel: str,
        reason: str,
        outcome: Outcome,
        status: MessageStatus,
    ) -> SendResult:
        """A send that ends before the provider is called (blocked, or no number to send from) is still recorded."""
        message_id = await store.insert_message(
            session,
            conversation_id=request.conversation_id,
            channel=channel,
            sender_kind=SENDER_KIND[request.purpose],
            body=request.body,
            provider=self._provider.name,
            idempotency_key=request.idempotency_key,
            trace_id=request.trace_id,
            staff_id=request.staff_id,
        )
        if message_id is None:
            existing = await store.find_message_by_key(session, request.idempotency_key)
            return await self._duplicate(session, existing.id)
        await store.append_event(
            session, message_id=message_id, attempt=1, status=status, trace_id=request.trace_id, reason_code=reason
        )
        return SendResult(outcome, message_id=message_id, status=status, reason=reason, attempt=1)

    async def _duplicate(self, session: AsyncSession, message_id: uuid.UUID) -> SendResult:
        events = await store.events_of(session, message_id)
        return SendResult(
            Outcome.DUPLICATE,
            message_id=message_id,
            status=current_status((e.attempt, e.status) for e in events),
        )

    async def _attempt(self, tenant_id: uuid.UUID, p: _Prepared, lane: Lane) -> SendResult:
        callback = self._status_callback(tenant_id, p.message_id) if self._status_callback else None
        started = clock_time.perf_counter()
        try:
            result = await self._provider.send(
                ProviderRequest(p.to, p.from_number, p.body, p.message_id, p.attempt, p.trace_id, callback)
            )
        except Exception:  # an adapter must not raise; if one does, the message may or may not exist
            log_event(log, "provider_raised", level=logging.ERROR, tenant_id=tenant_id, message_id=p.message_id)
            result = ProviderResult(False, error=ProviderError(ErrorKind.AMBIGUOUS, "provider_exception"))
        elapsed_ms = round((clock_time.perf_counter() - started) * 1000)
        log_event(
            log,
            "provider_call",
            level=logging.DEBUG,
            tenant_id=tenant_id,
            trace_id=p.trace_id,
            message_id=p.message_id,
            attempt=p.attempt,
            provider=self._provider.name,
            duration_ms=elapsed_ms,
        )
        return await self._record_attempt(tenant_id, p, lane, result)

    async def _record_attempt(
        self, tenant_id: uuid.UUID, p: _Prepared, lane: Lane, result: ProviderResult
    ) -> SendResult:
        if result.accepted:
            async with self._scope(tenant_id) as session:
                await store.append_event(
                    session,
                    message_id=p.message_id,
                    attempt=p.attempt,
                    status=MessageStatus.SENT,
                    trace_id=p.trace_id,
                    provider_message_id=result.provider_message_id,
                )
                await store.touch_last_outbound(session, p.conversation_id, self._now())
            return SendResult(Outcome.SENT, message_id=p.message_id, status=MessageStatus.SENT, attempt=p.attempt)

        error = result.error or ProviderError(ErrorKind.AMBIGUOUS, "no_result")
        base = {"message_id": p.message_id, "attempt": p.attempt, "provider_error_code": error.code}
        if error.kind is ErrorKind.AMBIGUOUS:
            # It may have been accepted. Record nothing: the message stays "sending" until a receipt says otherwise.
            return SendResult(Outcome.UNCERTAIN, status=MessageStatus.SENDING, reason="ambiguous", **base)

        async with self._scope(tenant_id) as session:
            await store.append_event(
                session,
                message_id=p.message_id,
                attempt=p.attempt,
                status=MessageStatus.FAILED,
                trace_id=p.trace_id,
                reason_code=error.code,
            )
            if error.kind is ErrorKind.OPT_OUT:
                await self._revoke(session, p.contact_id, p.channel, p.trace_id, error.code)

        if error.kind is ErrorKind.RETRYABLE:
            decision = next_retry(lane, p.attempt, error.kind, error.retry_after)
            if decision.retry_after_seconds is not None:
                return SendResult(
                    Outcome.RETRY,
                    status=MessageStatus.FAILED,
                    retry_after_seconds=decision.retry_after_seconds,
                    reason="retryable",
                    **base,
                )
            return SendResult(Outcome.FAILED, status=MessageStatus.FAILED, reason=decision.reason, **base)
        return SendResult(Outcome.FAILED, status=MessageStatus.FAILED, reason=error.kind.value, **base)

    async def _revoke(
        self, session: AsyncSession, contact_id: uuid.UUID, channel: str, trace_id: uuid.UUID | None, code: str | None
    ) -> bool:
        current = current_consent(await store.consent_snapshots(session, contact_id, channel))
        if current.granted is False:
            return False
        record_id = await store.add_consent(
            session,
            contact_id=contact_id,
            channel=channel,
            granted=False,
            source="stop",
            trace_id=trace_id,
            evidence={"provider_error_code": code} if code else {},
        )
        await self._audit_consent(session, record_id, channel, False, "stop")
        return True

    async def _audit_consent(
        self, session: AsyncSession, record_id: uuid.UUID, channel: str, granted: bool, source: str
    ) -> None:
        await audit(
            session,
            "lead_response.consent.changed",
            actor_type="system",
            entity_type="lead_response_consent",
            entity_id=record_id,
            details={"channel": channel, "granted": granted, "source": source},
        )

    # --- retrying -----------------------------------------------------------------------------------------------

    async def attempt_again(
        self, tenant_id: uuid.UUID, message_id: uuid.UUID, *, lane: Lane, trace_id: uuid.UUID
    ) -> SendResult:
        """The jobs worker calls this when ``send`` said RETRY. It never resends a message that may have gone out:
        sent, delivered, still sending, or ended with no_receipt are all answered without a new attempt."""
        async with self._scope(tenant_id) as session:
            message = await store.get_message(session, message_id)
            if message is None:
                raise MessageNotFound(str(message_id))
            events = await store.events_of(session, message_id)
            status = current_status((e.attempt, e.status) for e in events)
            if status is MessageStatus.FAILED:
                last = max(events, key=lambda e: (e.attempt, e.created_at))
                reasons = [e.reason_code for e in events if e.attempt == last.attempt and e.status == "failed"]
                if not reasons or not may_resend(reasons[-1]):
                    return SendResult(
                        Outcome.FAILED, message_id=message_id, status=status, reason=reasons[-1] if reasons else None
                    )
            elif status is MessageStatus.SENDING:
                return SendResult(Outcome.UNCERTAIN, message_id=message_id, status=status, reason="still_sending")
            elif status is not MessageStatus.FAILED:
                return SendResult(Outcome.DUPLICATE, message_id=message_id, status=status)

            attempt = max(e.attempt for e in events) + 1
            ctx = await store.load_send_context(session, message.conversation_id)
            if ctx is None or ctx.phone is None:
                raise ConversationNotFound(str(message.conversation_id))
            purpose = next(p for p, kind in SENDER_KIND.items() if kind == message.sender_kind)
            probe = SendRequest(message.conversation_id, purpose, message.body, lane, f"retry:{message_id}", trace_id)
            decision = await self._policy(session, probe, ctx.contact_id, ctx.channel)
            if isinstance(decision, Defer):
                return SendResult(Outcome.DEFERRED, message_id=message_id, until=decision.until, reason="quiet_hours")
            if isinstance(decision, Block):
                await store.append_event(
                    session,
                    message_id=message_id,
                    attempt=attempt,
                    status=MessageStatus.BLOCKED,
                    trace_id=trace_id,
                    reason_code=decision.reason,
                )
                return SendResult(
                    Outcome.BLOCKED,
                    message_id=message_id,
                    status=MessageStatus.BLOCKED,
                    reason=decision.reason,
                    attempt=attempt,
                )
            from_number = await self._numbers.resolve(tenant_id, message.conversation_id)
            if from_number is None:
                return SendResult(Outcome.FAILED, message_id=message_id, reason=FailReason.NO_FROM_NUMBER)
            took_it = await store.append_event(
                session, message_id=message_id, attempt=attempt, status=MessageStatus.SENDING, trace_id=trace_id
            )
            if not took_it:  # another worker got this attempt first
                return SendResult(
                    Outcome.UNCERTAIN, message_id=message_id, status=MessageStatus.SENDING, attempt=attempt
                )
            prepared = _Prepared(
                message_id,
                message.conversation_id,
                ctx.contact_id,
                ctx.channel,
                attempt,
                ctx.phone,
                from_number,
                message.body,
                trace_id,
                purpose,
            )
        result = await self._attempt(tenant_id, prepared, lane)
        self._log(tenant_id, trace_id, lane, purpose, result, to=prepared.to)
        return result

    async def expire_stuck(
        self, tenant_id: uuid.UUID, message_id: uuid.UUID, *, lane: Lane, trace_id: uuid.UUID
    ) -> bool:
        """A message still ``sending`` after its deadline gets a ``failed`` event with reason ``no_receipt``, which
        surfaces the lead to staff. It is never resent, in any lane (the first send may well have arrived)."""
        async with self._scope(tenant_id) as session:
            events = await store.events_of(session, message_id)
            if current_status((e.attempt, e.status) for e in events) is not MessageStatus.SENDING:
                return False
            latest = max(e.attempt for e in events)
            began = min(e.created_at for e in events if e.attempt == latest and e.status == "sending")
            if not is_stuck(lane, (self._now() - began).total_seconds()):
                return False
            added = await store.append_event(
                session,
                message_id=message_id,
                attempt=latest,
                status=MessageStatus.FAILED,
                trace_id=trace_id,
                reason_code=FailReason.NO_RECEIPT,
            )
        if added:
            log_event(
                log,
                "stuck_expired",
                level=logging.WARNING,
                tenant_id=tenant_id,
                trace_id=trace_id,
                message_id=message_id,
            )
        return added

    # --- receipts and keywords ----------------------------------------------------------------------------------

    async def record_receipt(
        self,
        tenant_id: uuid.UUID,
        *,
        provider_status: str,
        trace_id: uuid.UUID,
        provider_message_id: str | None = None,
        message_id: uuid.UUID | None = None,
        error_code: int | None = None,
    ) -> ReceiptResult:
        """Record a delivery receipt. The public route that receives it (and checks the signature) is chunk 4's."""
        mapped = map_provider_status(provider_status)
        if mapped is None:
            return ReceiptResult(False)
        async with self._scope(tenant_id) as session:
            attempt: int | None = None
            if provider_message_id is not None:
                found = await store.event_for_provider_message(session, provider_message_id)
                if found is not None:
                    message_id, attempt = found
            if message_id is None:
                return ReceiptResult(False)
            events = await store.events_of(session, message_id)
            if not events:
                return ReceiptResult(False)
            attempt = attempt or max(e.attempt for e in events)
            reason = str(error_code) if error_code is not None and mapped is MessageStatus.FAILED else None
            added = await store.append_event(
                session,
                message_id=message_id,
                attempt=attempt,
                status=mapped,
                trace_id=trace_id,
                reason_code=reason,
                provider_message_id=provider_message_id,
            )
            if added and mapped is MessageStatus.FAILED and error_code is not None:
                if classify_error(code=error_code) is ErrorKind.OPT_OUT:
                    owner = await store.contact_of_message(session, message_id)
                    if owner is not None:
                        await self._revoke(session, owner[0], owner[1], trace_id, str(error_code))
            events = await store.events_of(session, message_id)
            status = current_status((e.attempt, e.status) for e in events)
        log_event(
            log,
            "receipt",
            level=logging.INFO,
            tenant_id=tenant_id,
            trace_id=trace_id,
            message_id=message_id,
            status=mapped.value,
            outcome="recorded" if added else "repeat",
        )
        return ReceiptResult(added, message_id=message_id, status=status)

    async def handle_inbound_keyword(
        self,
        tenant_id: uuid.UUID,
        *,
        contact_id: uuid.UUID,
        text: str,
        inbound_message_id: uuid.UUID | None,
        trace_id: uuid.UUID,
        channel: str = CHANNEL,
    ) -> KeywordResult:
        """STOP appends a revocation, START a grant, HELP returns the (placeholder) help text to send. Intake (chunk 4)
        calls this for every inbound text. We send no STOP or START confirmation ourselves: Twilio may already answer
        them, and a send to a number that just opted out is refused (error 21610)."""
        keyword = classify_inbound(text)
        if keyword is None:
            return KeywordResult(None)
        async with self._scope(tenant_id) as session:
            if not await store.contact_exists(session, contact_id):
                raise ContactNotFound(str(contact_id))  # a foreign key would accept another tenant's contact
            current = current_consent(await store.consent_snapshots(session, contact_id, channel))
            if keyword is Keyword.HELP:
                if current.granted is False:
                    return KeywordResult(keyword)  # an opted-out contact gets nothing from us
                _tz, name = await store.tenant_info(session)
                return KeywordResult(keyword, reply_text=help_text(name))
            granted = keyword is Keyword.START
            # Nothing new to record when the contact is already in that state. A START still upgrades a grant that
            # only came from the lead's first text, because only an explicit grant allows follow-ups.
            already = (
                (current.granted is True and current.source != FIRST_INBOUND) if granted else current.granted is False
            )
            if already:
                return KeywordResult(keyword)
            record_id = await store.add_consent(
                session,
                contact_id=contact_id,
                channel=channel,
                granted=granted,
                source="start" if granted else "stop",
                trace_id=trace_id,
                message_id=inbound_message_id,
            )
            await self._audit_consent(session, record_id, channel, granted, "start" if granted else "stop")
        log_event(
            log,
            "consent_changed",
            level=logging.INFO,
            tenant_id=tenant_id,
            trace_id=trace_id,
            outcome="granted" if granted else "revoked",
        )
        return KeywordResult(keyword, consent_changed=True)

    # --- logging ------------------------------------------------------------------------------------------------

    def _log(
        self,
        tenant_id: uuid.UUID,
        trace_id: uuid.UUID,
        lane: Lane,
        purpose: Purpose,
        result: SendResult,
        *,
        to: str | None = None,
    ) -> None:
        log_event(
            log,
            "send",
            tenant_id=tenant_id,
            trace_id=trace_id,
            message_id=result.message_id,
            lane=lane.value,
            purpose=purpose.value,
            attempt=result.attempt,
            outcome=result.outcome.value,
            reason=result.reason,
            provider=self._provider.name,
            provider_error_code=result.provider_error_code,
            to_masked=mask_phone(to) if to else None,
        )


def build_gateway(**overrides) -> Gateway:
    """The gateway as it runs in the app: Twilio when the platform is set up for it, the single global number."""
    from clinic_lead_response.gateway.provider import GlobalNumberResolver
    from clinic_lead_response.gateway.twilio import build_default_provider

    return Gateway(
        overrides.pop("provider", None) or build_default_provider(),
        overrides.pop("numbers", None) or GlobalNumberResolver(),
        **overrides,
    )
