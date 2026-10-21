"""One-time tickets that let a browser open the call WebSocket.

The ticket is minted by an authenticated HTTP request (cookie + CSRF + role), so the
WebSocket itself needs no cookies. It names the tenant and call, expires quickly, and
works once: redeeming flips the call from ``connecting`` to ``in_progress`` atomically.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import tenant_session
from clinic_db.models.voice import Call

TICKET_TTL = timedelta(seconds=60)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def mint(call: Call) -> str:
    """Attach a fresh ticket to ``call`` (caller flushes) and return it."""
    secret = secrets.token_urlsafe(32)
    call.connect_token_hash = _hash(secret)
    call.connect_expires_at = datetime.now(UTC) + TICKET_TTL
    return f"{call.tenant_id}.{call.id}.{secret}"


async def redeem(ticket: str, database_url: str | None = None) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Return (tenant_id, call_id) if the ticket is valid and unused, else None."""
    try:
        tenant, call, secret = ticket.split(".", 2)
        tenant_id, call_id = uuid.UUID(tenant), uuid.UUID(call)
    except ValueError:
        return None
    async with tenant_session(tenant_id, database_url=database_url) as session:
        redeemed = await session.scalar(
            update(Call)
            .where(
                Call.id == call_id,
                Call.status == "connecting",
                Call.connect_token_hash == _hash(secret),
                Call.connect_expires_at > datetime.now(UTC),
            )
            .values(status="in_progress", connect_token_hash=None)
            .returning(Call.id)
        )
    return (tenant_id, call_id) if redeemed else None


async def snapshot_of(session: AsyncSession, call_id: uuid.UUID) -> dict | None:
    call = await session.get(Call, call_id)
    return call.agent_snapshot if call else None
