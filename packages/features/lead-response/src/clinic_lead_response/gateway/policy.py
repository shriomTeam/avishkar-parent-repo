"""May this text go out now? One pure function, so the rules can change in one place.

Rules (conservative; the open points are listed for Shriom in PROGRESS.md):
  * Opted out (the newest consent record is a revocation): nothing goes out, whatever the purpose.
  * A reply to the lead's own text (ack, holding, help, staff reply) needs no grant and ignores quiet hours.
  * Anything else (a follow-up, or anything in the bulk lane) needs an explicit grant on record: START, staff or import.
    The lead's first text is not enough. It also waits out quiet hours.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from clinic_lead_response.gateway.types import REPLY_PURPOSES, BlockReason, Lane, Purpose
from clinic_lead_response.settings_model import LeadResponseQuietWindow

FIRST_INBOUND = "first_inbound"  # consent_records.source of the grant a lead's own first text creates


@dataclass(frozen=True)
class ConsentSnapshot:
    granted: bool
    source: str
    created_at: datetime


@dataclass(frozen=True)
class ConsentState:
    granted: bool | None = None  # None: no record at all
    source: str | None = None


@dataclass(frozen=True)
class Allow:
    pass


@dataclass(frozen=True)
class Defer:
    until: datetime


@dataclass(frozen=True)
class Block:
    reason: str


Decision = Allow | Defer | Block


def current_consent(records: Iterable[ConsentSnapshot]) -> ConsentState:
    """The newest record wins. consent_records has no sequence column, so two records with the same timestamp (written
    in one transaction) are a tie, and a revocation wins a tie: when in doubt, do not text."""
    records = list(records)
    if not records:
        return ConsentState()
    newest = max(r.created_at for r in records)
    tied = [r for r in records if r.created_at == newest]
    chosen = next((r for r in tied if not r.granted), tied[-1])
    return ConsentState(granted=chosen.granted, source=chosen.source)


def _clock(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def in_quiet_hours(local: time, window: LeadResponseQuietWindow) -> bool:
    start, end = _clock(window.start), _clock(window.end)
    if start < end:
        return start <= local < end
    return local >= start or local < end  # crosses midnight (21:00 to 08:00)


def _instant(day: date, at: time, tz: ZoneInfo) -> datetime:
    """That wall-clock time on that day, as a UTC instant. A time that does not exist (the spring-forward gap) lands
    the same distance after the gap (02:30 becomes 03:30); a time that happens twice (fall back) means its first one."""
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def quiet_hours_end(now: datetime, tz: ZoneInfo, window: LeadResponseQuietWindow) -> datetime:
    """The next instant after ``now`` at which the window ends."""
    start, end = _clock(window.start), _clock(window.end)
    local = now.astimezone(tz)
    day = local.date()
    if start > end and local.time() >= start:
        day += timedelta(days=1)  # the window began tonight and ends tomorrow morning
    return _instant(day, end, tz)


def decide(
    *,
    purpose: Purpose,
    lane: Lane,
    now: datetime,
    tz: ZoneInfo,
    quiet_hours: LeadResponseQuietWindow | None,
    consent: ConsentState,
) -> Decision:
    if consent.granted is False:
        return Block(BlockReason.OPTED_OUT)
    if purpose in REPLY_PURPOSES and lane is not Lane.BULK:
        return Allow()
    if consent.granted is not True or consent.source == FIRST_INBOUND:
        return Block(BlockReason.NO_CONSENT)
    if quiet_hours is not None and in_quiet_hours(now.astimezone(tz).time(), quiet_hours):
        return Defer(quiet_hours_end(now, tz, quiet_hours))
    return Allow()
