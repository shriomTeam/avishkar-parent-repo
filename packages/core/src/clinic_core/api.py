"""FastAPI dependencies every feature router uses.

Authentication is a placeholder: in dev, the caller identifies itself with the
``X-Tenant-Id`` / ``X-Staff-Role`` headers. Replace ``get_request_context`` with
real token verification before any non-dev deployment; nothing else changes.
"""

import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import tenant_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_core.settings import get_settings
from clinic_db.models.core import StaffRole


@dataclass(frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    actor_id: str
    role: StaffRole


async def get_request_context(
    x_tenant_id: uuid.UUID | None = Header(default=None),
    x_staff_role: StaffRole = Header(default=StaffRole.OWNER),
    x_staff_id: str = Header(default="dev-user"),
) -> RequestContext:
    if not get_settings().is_dev:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication is not configured")
    if x_tenant_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "X-Tenant-Id header required (dev auth)")
    return RequestContext(tenant_id=x_tenant_id, actor_id=x_staff_id, role=x_staff_role)


async def get_session(ctx: RequestContext = Depends(get_request_context)) -> AsyncIterator[AsyncSession]:
    async with tenant_session(ctx.tenant_id) as session:
        yield session


def require_feature(feature_key: str) -> Callable:
    """Applied by the API to every feature router: 403 unless the tenant has it."""

    async def dependency(session: AsyncSession = Depends(get_session)) -> None:
        if feature_key not in await enabled_feature_keys(session):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Feature '{feature_key}' is not enabled")

    return dependency


def require_role(*roles: StaffRole) -> Callable:
    async def dependency(ctx: RequestContext = Depends(get_request_context)) -> None:
        if ctx.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")

    return dependency
