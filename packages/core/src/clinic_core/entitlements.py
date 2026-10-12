"""Which features a tenant has bought (or is trialling).

The same key is the package entry point, the API prefix, the billing line item
and the switch in this table.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.core import TenantFeature


async def enabled_feature_keys(session: AsyncSession) -> set[str]:
    now = datetime.now(UTC)
    rows = await session.scalars(
        select(TenantFeature.feature_key).where(
            TenantFeature.tenant_id == current_tenant(session),
            TenantFeature.enabled.is_(True),
            or_(TenantFeature.expires_at.is_(None), TenantFeature.expires_at > now),
        )
    )
    return set(rows)


async def is_enabled(session: AsyncSession, feature_key: str) -> bool:
    return feature_key in await enabled_feature_keys(session)


async def set_feature(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    feature_key: str,
    *,
    enabled: bool = True,
    expires_at: datetime | None = None,
    config: dict | None = None,
) -> None:
    stmt = insert(TenantFeature).values(
        tenant_id=tenant_id,
        feature_key=feature_key,
        enabled=enabled,
        expires_at=expires_at,
        config=config or {},
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[TenantFeature.tenant_id, TenantFeature.feature_key],
            set_={"enabled": enabled, "expires_at": expires_at, "config": stmt.excluded.config},
        )
    )
