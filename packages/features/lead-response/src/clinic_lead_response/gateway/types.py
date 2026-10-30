"""The words the gateway speaks: lanes, purposes, outcomes, statuses, and the request and result of a send."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clinic_lead_response.gateway.keywords import Keyword


class Lane(StrEnum):
    """What a send is for, in policy terms only. Release 1 has no separate queues; bulk is defined but unused."""

    LIVE = "live"
    FOLLOW_UP = "follow_up"
    BULK = "bulk"


class Purpose(StrEnum):
    ACK = "ack"
    HOLDING = "holding"
    FOLLOW_UP = "follow_up"
    HELP = "help"
    STAFF_REPLY = "staff_reply"


# A reply answers the lead's own text. Replies are exempt from quiet hours and do not need an explicit grant.
REPLY_PURPOSES = frozenset({Purpose.ACK, Purpose.HOLDING, Purpose.HELP, Purpose.STAFF_REPLY})

# messages.sender_kind (a plain string column, at most 16 characters).
SENDER_KIND = {
    Purpose.ACK: "ack",
    Purpose.HOLDING: "holding",
    Purpose.FOLLOW_UP: "followup",
    Purpose.HELP: "help",
    Purpose.STAFF_REPLY: "staff",
}


class Outcome(StrEnum):
    SENT = "sent"  # the provider accepted the message
    RETRY = "retry"  # nothing was sent; try again after ``retry_after_seconds``
    FAILED = "failed"  # permanent: not sent, and no retry will help
    BLOCKED = "blocked"  # policy said no (opted out, no consent, no phone number); recorded with a reason
    DEFERRED = "deferred"  # policy said "later" (quiet hours); nothing recorded, try again at ``until``
    UNCERTAIN = "uncertain"  # in flight, answer unknown: never resent blindly, a delivery receipt will tell
    DUPLICATE = "duplicate"  # this idempotency key was already used; the earlier result is returned


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BLOCKED = "blocked"


class BlockReason:
    OPTED_OUT = "opted_out"
    NO_CONSENT = "no_consent"
    NO_PHONE = "no_phone"
    BAD_TIMEZONE = "bad_timezone"  # the clinic's time zone is not recognised, so quiet hours cannot be checked


class FailReason:
    NO_RECEIPT = "no_receipt"  # in flight too long with no receipt: surfaces the lead to staff, never resent
    RETRIES_EXHAUSTED = "retries_exhausted"
    NO_FROM_NUMBER = "no_from_number"


@dataclass(frozen=True)
class SendRequest:
    conversation_id: uuid.UUID
    purpose: Purpose
    body: str  # personal data: stored, never logged
    lane: Lane
    idempotency_key: str
    trace_id: uuid.UUID
    staff_id: uuid.UUID | None = None


@dataclass(frozen=True)
class SendResult:
    outcome: Outcome
    message_id: uuid.UUID | None = None
    status: MessageStatus | None = None  # for a duplicate: where the earlier message stands now
    reason: str | None = None
    provider_error_code: str | None = None
    retry_after_seconds: float | None = None
    until: datetime | None = None
    attempt: int | None = None


@dataclass(frozen=True)
class ReceiptResult:
    recorded: bool  # False: nothing to do (an unknown message, an ignored status, or a repeat of an event we have)
    message_id: uuid.UUID | None = None
    status: MessageStatus | None = None  # where the message stands now, derived from its events


@dataclass(frozen=True)
class KeywordResult:
    keyword: "Keyword | None"  # what the text meant, or None for an ordinary message
    consent_changed: bool = False
    reply_text: str | None = None  # the HELP answer to send (a placeholder text), else None
