"""Narrow cross-tenant membership lookup, only for a verified global user."""

import uuid

from sqlalchemy import select

from clinic_core.database import system_session
from clinic_core.settings import Settings
from clinic_db.models.core import Staff, Tenant, TenantStatus


async def memberships(user_id: uuid.UUID, settings: Settings):
    async with system_session(database_url=settings.database_system_url) as db:
        return (
            await db.execute(
                select(Staff, Tenant)
                .join(Tenant, Staff.tenant_id == Tenant.id)
                .where(Staff.user_id == user_id, Staff.active.is_(True), Tenant.status != TenantStatus.SUSPENDED)
                .order_by(Staff.created_at, Staff.id)
            )
        ).all()
