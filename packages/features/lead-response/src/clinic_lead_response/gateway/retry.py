"""What a provider error means, and whether to try again. Pure: the gateway makes one attempt and records it; a pure
policy says "retry after N seconds" or "give up", and the jobs worker (a later chunk) does the re-firing.

Error codes are Twilio's. Verified against Twilio's documentation on 2026-10-30: the titles of 21211, 21212, 21214,
21217, 21408, 21610, 21611, 21612, 21614, 21619, 20003 and 20429; that a send to an opted-out number fails with 21610;
that 30006 means "do not retry the same SMS" and 30003 can be retried. Anything not listed is treated as permanent.
Unverified: a Retry-After header on 429, and whether a 5xx means the message was not created (so 5xx is "ambiguous").
"""

from dataclasses import dataclass
from enum import StrEnum

from clinic_lead_response.gateway.types import FailReason, Lane


class ErrorKind(StrEnum):
    OPT_OUT = "opt_out"  # the recipient replied STOP: record a revocation, never retry
    INVALID_NUMBER = "invalid_number"  # not a number we can text: never retry
    PERMANENT = "permanent"  # refused for another reason: never retry
    CONFIG = "config"  # our credentials or setup are wrong: never retry, needs a person
    RETRYABLE = "retryable"  # nothing was sent and trying again can work
    AMBIGUOUS = "ambiguous"  # the provider may have accepted it: never resend, wait for a receipt


OPT_OUT_CODES = frozenset({21610})
INVALID_NUMBER_CODES = frozenset({21211, 21214, 21217, 21614, 30005, 30006})
CONFIG_CODES = frozenset({20003})
RETRYABLE_CODES = frozenset({20429, 21611, 30003})
AMBIGUOUS_HTTP = frozenset({500, 502, 503, 504})


def classify_error(
    *, code: int | None = None, http_status: int | None = None, transport: str | None = None
) -> ErrorKind:
    """``transport`` is "connect" if the request never reached the provider, "timeout" or "broken" if it may have."""
    if transport == "connect":
        return ErrorKind.RETRYABLE
    if transport in ("timeout", "broken"):
        return ErrorKind.AMBIGUOUS
    if code in OPT_OUT_CODES:
        return ErrorKind.OPT_OUT
    if code in INVALID_NUMBER_CODES:
        return ErrorKind.INVALID_NUMBER
    if code in CONFIG_CODES:
        return ErrorKind.CONFIG
    if code in RETRYABLE_CODES or http_status == 429:
        return ErrorKind.RETRYABLE
    if http_status is not None and (http_status in AMBIGUOUS_HTTP or http_status >= 500):
        return ErrorKind.AMBIGUOUS
    return ErrorKind.PERMANENT


# Seconds to wait before each retry. Three retries means four attempts. The live lane gives up after about a
# minute, because an ack that arrives later is of little use; follow-ups can wait.
RETRY_DELAYS = {
    Lane.LIVE: (3, 15, 45),
    Lane.FOLLOW_UP: (60, 300, 1800),
    Lane.BULK: (60, 300, 1800),
}
MAX_RETRY_AFTER = 3600  # a provider's Retry-After is honoured up to this

# How long a message may stay "sending" with no receipt before it is surfaced to staff (never resent).
STUCK_AFTER_SECONDS = {Lane.LIVE: 120, Lane.FOLLOW_UP: 1800, Lane.BULK: 1800}


@dataclass(frozen=True)
class RetryDecision:
    retry_after_seconds: float | None  # None: do not retry
    reason: str | None = None  # why not


def next_retry(lane: Lane, attempt: int, kind: ErrorKind, retry_after: float | None = None) -> RetryDecision:
    """``attempt`` is the attempt that just failed (1 for the first)."""
    if kind is not ErrorKind.RETRYABLE:
        return RetryDecision(None, kind.value)
    delays = RETRY_DELAYS[lane]
    if attempt > len(delays):
        return RetryDecision(None, FailReason.RETRIES_EXHAUSTED)
    delay = float(delays[attempt - 1])
    if retry_after is not None:
        delay = max(delay, min(float(retry_after), MAX_RETRY_AFTER))
    return RetryDecision(delay)


def is_stuck(lane: Lane, seconds_in_flight: float) -> bool:
    return seconds_in_flight >= STUCK_AFTER_SECONDS[lane]


def total_retry_seconds(lane: Lane) -> int:
    return sum(RETRY_DELAYS[lane])


def may_resend(failed_reason: str | None) -> bool:
    """A message that ended with no_receipt is never resent, in any lane: the first send may well have arrived."""
    if failed_reason is None or failed_reason == FailReason.NO_RECEIPT:
        return False
    try:
        code = int(failed_reason)
    except ValueError:
        return failed_reason.startswith("http_429") or failed_reason == "connect_error"
    return classify_error(code=code) is ErrorKind.RETRYABLE
