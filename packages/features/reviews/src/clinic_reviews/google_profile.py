"""Practice-owned Google Business Profile link. Patients open it themselves."""

from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.reviews import Integration

# Hosts that open Google's own review composer. Anything else is rejected.
_REVIEW_HOSTS = {
    "g.page": None,
    "www.g.page": None,
    "maps.app.goo.gl": None,
    "search.google.com": "/local/writereview",
}


def validate_review_url(url: str) -> str:
    url = url.strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    required_prefix = _REVIEW_HOSTS.get(host)
    path_ok = required_prefix is None or parts.path.startswith(required_prefix)
    if parts.scheme != "https" or parts.username or parts.password or host not in _REVIEW_HOSTS or not path_ok:
        raise ValueError("review link must be an https Google review URL")
    return url


async def get_or_create(session: AsyncSession) -> Integration:
    row = await session.scalar(select(Integration))
    if row is None:
        row = Integration(tenant_id=current_tenant(session), status="not_connected")
        session.add(row)
        await session.flush()
    return row


async def connect(session: AsyncSession, *, listing_name: str, review_url: str) -> Integration:
    url = validate_review_url(review_url)
    row = await get_or_create(session)
    row.listing_name = listing_name
    row.google_review_url = url
    row.status = "connected"
    row.last_validated_at = datetime.now(UTC)
    return row
