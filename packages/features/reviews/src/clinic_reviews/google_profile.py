"""Practice-owned Google Business Profile link. Patients open it themselves."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.reviews import Integration


async def get_or_create(session: AsyncSession) -> Integration:
    row = await session.scalar(select(Integration))
    if row is None:
        row = Integration(tenant_id=current_tenant(session), status="not_connected")
        session.add(row)
        await session.flush()
    return row


async def connect(session: AsyncSession, *, listing_name: str, review_url: str) -> Integration:
    row = await get_or_create(session)
    row.listing_name = listing_name
    row.google_review_url = review_url
    row.status = "connected"
    row.last_validated_at = datetime.now(UTC)
    return row
