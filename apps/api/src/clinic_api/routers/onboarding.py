from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from clinic_api.routers.workspace_audit import router as audit_router
from clinic_core.auth.dependencies import DB, CurrentSession, ProtectedWrite, get_settings
from clinic_core.auth.repository import limit
from clinic_core.tenancy.management import settings_out, update_workspace, workspace_access
from clinic_core.tenancy.repository import memberships
from clinic_core.tenancy.schemas import (
    WorkspaceCreate,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspaceSettingsOut,
    WorkspaceUpdate,
)
from clinic_core.tenancy.service import create_workspace
from clinic_db.models.core import Staff

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])
router.include_router(audit_router)


def workspace_out(tenant):
    return WorkspaceOut(
        id=tenant.id, name=tenant.name, timezone=tenant.timezone, phone=tenant.settings.get("callback_phone")
    )


@router.post("", response_model=WorkspaceOut)
async def onboarding(data: WorkspaceCreate, request: Request, principal: ProtectedWrite, db: DB):
    await limit(db, "workspace:" + str(principal.user.id), 10)
    tenant = await create_workspace(principal.user.id, data, get_settings(request))
    principal.session.active_workspace_id = tenant.id
    await db.commit()
    return workspace_out(tenant)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def detail(workspace_id: UUID, request: Request, principal: CurrentSession):
    rows = await memberships(principal.user.id, get_settings(request))
    for _, tenant in rows:
        if tenant.id == workspace_id:
            return workspace_out(tenant)
    raise HTTPException(403, detail="workspace_access_denied")


@router.get("/{workspace_id}/settings", response_model=WorkspaceSettingsOut)
async def settings_detail(workspace_id: UUID, request: Request, principal: CurrentSession):
    async with workspace_access(principal.user.id, workspace_id, get_settings(request)) as (_, tenant, _):
        return settings_out(tenant)


@router.post("/{workspace_id}/settings", response_model=WorkspaceSettingsOut)
async def settings_update(workspace_id: UUID, data: WorkspaceUpdate, request: Request, principal: ProtectedWrite):
    return await update_workspace(principal.user.id, workspace_id, data, get_settings(request))


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
async def members(workspace_id: UUID, request: Request, principal: CurrentSession):
    async with workspace_access(principal.user.id, workspace_id, get_settings(request), manage=True) as (db, _, _):
        rows = (
            await db.scalars(select(Staff).where(Staff.tenant_id == workspace_id).order_by(Staff.created_at, Staff.id))
        ).all()
        return [
            WorkspaceMemberOut(
                id=m.id,
                user_id=m.user_id,
                name=m.name,
                email=m.email,
                role=m.role,
                active=m.active,
                created_at=m.created_at.isoformat(),
            )
            for m in rows
        ]
