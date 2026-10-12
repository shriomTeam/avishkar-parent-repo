"""Who may be contacted, and when. Every outbound message goes through here.

Defaults are conservative (TCPA): SMS needs an explicit opt-in on record unless
the tenant has documented consent another way and switched
``settings.sms_requires_explicit_opt_in`` off; no sends outside 8am-9pm local.
"""

import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.core import Consent, Tenant

QUIET_START = time(21, 0)
QUIET_END = time(8, 0)
STOP_KEYWORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}


async def can_contact(
    session: AsyncSession, tenant: Tenant, patient_id: uuid.UUID | None, channel: str
) -> tuple[bool, str | None]:
    if patient_id is None:  # leads: consent captured on the lead form itself
        return True, None
    granted = await session.scalar(
        select(Consent.granted)
        .where(Consent.patient_id == patient_id, Consent.kind == channel)
        .order_by(Consent.recorded_at.desc())
        .limit(1)
    )
    if granted is False:
        return False, "opted_out"
    if granted is None and channel == "sms" and tenant.settings.get("sms_requires_explicit_opt_in", True):
        return False, "no_sms_consent"
    return True, None


def next_send_window(now: datetime, tz_name: str) -> datetime:
    """``now`` if inside allowed hours, else the next 8am in the clinic's timezone."""
    local = now.astimezone(ZoneInfo(tz_name))
    if QUIET_END <= local.time() < QUIET_START:
        return now
    day = local.date() if local.time() < QUIET_END else local.date() + timedelta(days=1)
    return datetime.combine(day, QUIET_END, tzinfo=local.tzinfo)
