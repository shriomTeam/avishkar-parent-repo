"""The stuck-message sweep: settle messages the provider may or may not have sent.

A send whose answer never arrived (a timeout, a crash between the provider call and the next write) leaves the message
``sending``. It is never resent: that could text a lead twice. The delivery receipt normally settles it. If none comes
within the live lane's deadline (120 s), the gateway's own ``expire_stuck`` appends ``failed`` with the reason
``no_receipt``, which is final unless a ``delivered`` receipt turns up later. Nothing is sent here, and the staff task
for the lead exists regardless: the sweep only stops a message from looking in flight for ever.

The sweep looks at the latest attempt of each outbound message from the last 24 hours that has a ``sending`` event older
than the deadline and nothing after it (no sent, failed, blocked or delivered), and asks the gateway to expire it. The
gateway re-checks the age and the status itself, so a message settled in the meantime is left alone.

COST NOTE: ``message_events`` has no index on its time, so this reads the clinic's events by tenant. That is cheap for
now; if event volume grows, an index on (tenant_id, status, created_at) is the follow-up (a migration, not this chunk).
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import aliased

from clinic_db.models.lead_response import MessageEvent
from clinic_lead_response.gateway.log import log_event
from clinic_lead_response.gateway.retry import STUCK_AFTER_SECONDS
from clinic_lead_response.gateway.types import Lane, MessageStatus

log = logging.getLogger("lead_response.engine")

WINDOW = timedelta(hours=24)
FINAL_OR_MOVING = (
    MessageStatus.SENT.value,
    MessageStatus.DELIVERED.value,
    MessageStatus.FAILED.value,
    MessageStatus.BLOCKED.value,
)


async def stuck_candidates(engine, tenant_id: uuid.UUID, *, limit: int) -> list[uuid.UUID]:
    now = engine.now()
    later = aliased(MessageEvent)
    delivered = aliased(MessageEvent)
    query = (
        select(MessageEvent.message_id)
        .where(
            MessageEvent.status == MessageStatus.SENDING.value,
            MessageEvent.created_at < now - timedelta(seconds=STUCK_AFTER_SECONDS[Lane.LIVE]),
            MessageEvent.created_at >= now - WINDOW,
            MessageEvent.attempt
            == select(func.max(later.attempt)).where(later.message_id == MessageEvent.message_id).scalar_subquery(),
            ~exists().where(
                and_(
                    later.message_id == MessageEvent.message_id,
                    later.attempt == MessageEvent.attempt,
                    later.status.in_(FINAL_OR_MOVING),
                )
            ),
            ~exists().where(
                and_(delivered.message_id == MessageEvent.message_id, delivered.status == MessageStatus.DELIVERED.value)
            ),
        )
        .order_by(MessageEvent.created_at)
        .limit(limit)
    )
    async with engine.scope(tenant_id) as session:
        return list(await session.scalars(query))


async def expire_stuck(engine, tenant_id: uuid.UUID, *, limit: int = 50) -> int:
    """Settle this clinic's stuck messages. Returns how many were expired. Off when the engine is off."""
    if not await engine.may_run(tenant_id):
        return 0
    expired = 0
    for message_id in await stuck_candidates(engine, tenant_id, limit=limit):
        if await engine.gateway.expire_stuck(tenant_id, message_id, lane=Lane.LIVE, trace_id=uuid.uuid4()):
            expired += 1
    if expired:
        log_event(log, "sweep", tenant_id=tenant_id, outcome="expired", queries=expired)
    return expired
