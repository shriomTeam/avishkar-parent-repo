"""Shared workspace administration, independent of installed feature packages."""

from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import select

from clinic_core.database import system_session
from clinic_db.models.core import Staff, StaffRole, Tenant, TenantStatus
from clinic_db.models.ops import AuditLog

MANAGERS = {StaffRole.OWNER, StaffRole.OFFICE_MANAGER}


@asynccontextmanager
async def workspace_access(user_id, workspace_id, settings, *, manage=False):
    # Serialize management against the workspace row. Every query is explicitly scoped:
    # this narrow platform operation uses the provisioning/system role.
    async with system_session(database_url=settings.database_system_url) as db:
        tenant = await db.scalar(select(Tenant).where(Tenant.id == workspace_id).with_for_update())
        member = await db.scalar(
            select(Staff).where(Staff.tenant_id == workspace_id, Staff.user_id == user_id, Staff.active.is_(True))
        )
        if not tenant or tenant.status == TenantStatus.SUSPENDED or not member:
            raise HTTPException(403, detail="workspace_access_denied")
        if manage and member.role not in MANAGERS:
            raise HTTPException(403, detail="workspace_management_denied")
        yield db, tenant, member


def settings_out(tenant):
    from clinic_core.tenancy.schemas import WorkspaceSettingsOut

    return WorkspaceSettingsOut(
        id=tenant.id,
        name=tenant.name,
        timezone=tenant.timezone,
        phone=tenant.settings.get("callback_phone"),
        clinic_type=tenant.clinic_type,
        address=tenant.settings.get("address", ""),
        status=tenant.status,
        baa_signed_at=tenant.baa_signed_at.isoformat() if tenant.baa_signed_at else None,
    )


async def update_workspace(user_id, workspace_id, data, settings):
    async with workspace_access(user_id, workspace_id, settings, manage=True) as (db, tenant, member):
        tenant.name, tenant.timezone, tenant.clinic_type = data.name, data.timezone, data.clinic_type
        # Preserve unrelated feature configuration and consent/BAA state.
        tenant.settings = {**tenant.settings, "callback_phone": data.phone, "address": data.address.strip()}
        db.add(
            AuditLog(
                tenant_id=workspace_id,
                actor_type="staff",
                actor_id=str(member.id),
                action="workspace.updated",
                entity_type="workspace",
                entity_id=workspace_id,
                details={"fields": ["name", "timezone", "clinic_type", "callback_phone", "address"]},
            )
        )
        return settings_out(tenant)
