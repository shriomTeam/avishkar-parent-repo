import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.auth.dependencies import DB, get_current_session, get_settings
from clinic_core.auth.security import check_csrf
from clinic_core.database import tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_core.tenancy.permissions import can_use_feature
from clinic_core.tenancy.repository import memberships
from clinic_db.models.core import StaffRole


@dataclass(frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    actor_id: str
    role: StaffRole
    database_url: str | None = None
    session_id: uuid.UUID | None = None


async def get_request_context(
    request: Request,
    db: DB,
    x_tenant_id: uuid.UUID | None = Header(default=None),
    x_staff_role: StaffRole = Header(default=StaffRole.OWNER),
    x_staff_id: str = Header(default="dev-user"),
) -> RequestContext:
    settings = get_settings(request)
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie and settings.is_dev and settings.allow_dev_auth:
        if x_tenant_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Tenant-Id required for opt-in dev auth")
        return RequestContext(x_tenant_id, x_staff_id, x_staff_role, settings.database_url)
    principal = await get_current_session(request, db)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        check_csrf(request, principal.session.csrf_token_hash, settings)
    rows = await memberships(principal.user.id, settings)
    selected = principal.session.active_workspace_id
    if selected is None and len(rows) == 1:
        selected = rows[0][1].id
    if x_tenant_id is not None and x_tenant_id != selected:
        raise HTTPException(403, "workspace_selection_mismatch")
    for staff, tenant in rows:
        if tenant.id == selected:
            return RequestContext(
                tenant.id, str(staff.id), StaffRole(staff.role), settings.database_url, principal.session.id
            )
    raise HTTPException(status.HTTP_403_FORBIDDEN, "workspace_access_denied")


async def get_session(ctx: RequestContext = Depends(get_request_context)) -> AsyncIterator[AsyncSession]:
    async with tenant_session(ctx.tenant_id, database_url=ctx.database_url) as session:
        yield session


def require_feature(feature_key: str) -> Callable:
    """Applied by the API to every feature router: 403 unless the tenant has it."""

    async def dependency(
        session: AsyncSession = Depends(get_session), ctx: RequestContext = Depends(get_request_context)
    ) -> None:
        if not can_use_feature(ctx.role, feature_key):
            raise HTTPException(403, "feature_access_denied")
        if feature_key not in await enabled_feature_keys(session):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Feature '{feature_key}' is not enabled")

    return dependency


def require_role(*roles: StaffRole) -> Callable:
    async def dependency(ctx: RequestContext = Depends(get_request_context)) -> None:
        if ctx.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")

    return dependency
