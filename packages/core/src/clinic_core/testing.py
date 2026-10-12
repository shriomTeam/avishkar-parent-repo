"""Helpers for integration tests in any package (needs the local DB migrated)."""

import uuid
from datetime import UTC, datetime

from clinic_core.database import system_session
from clinic_core.entitlements import set_feature
from clinic_db.models.core import Tenant


async def create_test_tenant(
    features: tuple[str, ...] = (), *, baa: bool = True, clinic_type: str = "medspa", settings: dict | None = None
) -> uuid.UUID:
    """A fresh tenant per test, so tests never see each other's rows (RLS)."""
    async with system_session() as s:
        tenant = Tenant(
            name=f"test-{uuid.uuid4().hex[:8]}",
            clinic_type=clinic_type,
            status="active",
            baa_signed_at=datetime.now(UTC) if baa else None,
            settings=settings or {},
        )
        s.add(tenant)
        await s.flush()
        for key in features:
            await set_feature(s, tenant.id, key)
        return tenant.id
