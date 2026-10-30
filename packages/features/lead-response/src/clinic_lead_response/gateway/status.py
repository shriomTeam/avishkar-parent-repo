"""A message's status is derived from its events, never stored: ``messages`` is append-only.

Within an attempt the highest rank wins, so a late ``sent`` cannot hide ``delivered``. The latest attempt decides,
because a failed first attempt must not outrank the retry that follows it. Only ``delivered`` is final across attempts.
"""

from collections.abc import Iterable

from clinic_lead_response.gateway.types import MessageStatus

RANK = {
    MessageStatus.QUEUED: 0,
    MessageStatus.SENDING: 1,
    MessageStatus.SENT: 2,
    MessageStatus.FAILED: 3,
    MessageStatus.BLOCKED: 3,
    MessageStatus.DELIVERED: 4,
}

_PROVIDER_STATUS = {
    "accepted": MessageStatus.QUEUED,
    "scheduled": MessageStatus.QUEUED,
    "queued": MessageStatus.QUEUED,
    "sending": MessageStatus.SENDING,
    "sent": MessageStatus.SENT,
    "delivered": MessageStatus.DELIVERED,
    "read": MessageStatus.DELIVERED,
    "undelivered": MessageStatus.FAILED,
    "failed": MessageStatus.FAILED,
}


def map_provider_status(status: str) -> MessageStatus | None:
    """Twilio's status words in our terms. Anything else (receiving, canceled, a new word) is ignored."""
    return _PROVIDER_STATUS.get(status.strip().casefold())


def current_status(events: Iterable[tuple[int, str]]) -> MessageStatus | None:
    """``events`` are (attempt, status) pairs in any order."""
    pairs = [(attempt, MessageStatus(status)) for attempt, status in events]
    if not pairs:
        return None
    if any(status is MessageStatus.DELIVERED for _, status in pairs):
        return MessageStatus.DELIVERED
    latest = max(attempt for attempt, _ in pairs)
    return max((status for attempt, status in pairs if attempt == latest), key=RANK.__getitem__)
