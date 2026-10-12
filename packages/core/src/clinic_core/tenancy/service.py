"""Atomic initial clinic provisioning; never grants a BAA from onboarding."""

import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from clinic_core.auth.security import now
from clinic_core.database import system_session
from clinic_core.entitlements import set_feature
from clinic_core.settings import Settings
from clinic_core.tenancy.schemas import WorkspaceCreate
from clinic_db.models.auth import User
from clinic_db.models.core import Staff, StaffRole, Tenant, TenantStatus


async def create_workspace(user_id: uuid.UUID, data: WorkspaceCreate, settings: Settings) -> Tenant:
    async with system_session(database_url=settings.database_system_url) as db:
        user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
        if not user or not user.active:
            raise HTTPException(401, detail="not_authenticated")
        previous = (
            await db.execute(
                select(Staff, Tenant)
                .join(Tenant, Staff.tenant_id == Tenant.id)
                .where(Staff.user_id == user_id)
                .order_by(Staff.created_at, Staff.id)
            )
        ).all()
        for staff, tenant in previous:
            if staff.active and tenant.status != TenantStatus.SUSPENDED:
                return tenant
        if previous:
            raise HTTPException(403, detail="workspace_access_denied")
        stamp = now()
        expires = stamp + timedelta(days=14)
        tenant = Tenant(
            id=uuid.uuid4(),
            name=data.name,
            timezone=data.timezone,
            clinic_type=data.clinic_type,
            status=TenantStatus.TRIAL,
            trial_ends_at=expires,
            settings={"callback_phone": data.phone},
        )
        db.add(tenant)
        await db.flush()
        db.add(
            Staff(
                tenant_id=tenant.id,
                user_id=user.id,
                email=user.email,
                name=user.display_name,
                role=StaffRole.OWNER,
                active=True,
            )
        )
        # Initial preview trial; expiry is enforced by platform entitlement checks.
        for key in ("reactivation", "blueprints", "voice_receptionist"):
            await set_feature(db, tenant.id, key, expires_at=expires)
        return tenant
