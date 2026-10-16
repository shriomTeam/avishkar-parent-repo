from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from clinic_core.auth.dependencies import DB, CurrentSession, ProtectedWrite, get_settings
from clinic_core.auth.repository import limit
from clinic_core.tenancy.repository import memberships
from clinic_core.tenancy.schemas import WorkspaceCreate, WorkspaceOut
from clinic_core.tenancy.service import create_workspace

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


def workspace_out(tenant):
    return WorkspaceOut(
        id=tenant.id, name=tenant.name, timezone=tenant.timezone, phone=tenant.settings.get("callback_phone")
    )


@router.post("", response_model=WorkspaceOut)
async def onboarding(data: WorkspaceCreate, request: Request, principal: ProtectedWrite, db: DB):
    await limit(db, "workspace:" + str(principal.user.id), 10)
    tenant = await create_workspace(principal.user.id, data, get_settings(request))
    return workspace_out(tenant)


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def detail(workspace_id: UUID, request: Request, principal: CurrentSession):
    rows = await memberships(principal.user.id, get_settings(request))
    for _, tenant in rows:
        if tenant.id == workspace_id:
            return workspace_out(tenant)
    raise HTTPException(403, detail="workspace_access_denied")
