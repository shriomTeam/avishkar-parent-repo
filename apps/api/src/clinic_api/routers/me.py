import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session
from clinic_core.entitlements import enabled_feature_keys
from clinic_core.features import load_features
from clinic_core.tenancy.permissions import can_use_feature
from clinic_db.models.core import Tenant

router = APIRouter(tags=["platform"])


class NavItemOut(BaseModel):
    feature: str
    label: str
    path: str


class FeatureOut(BaseModel):
    key: str
    name: str
    description: str
    enabled: bool
    available: bool
    accessible: bool
    trial_eligible: bool
    phi_sensitive: bool


class MeOut(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    clinic_type: str
    tenant_status: str
    role: str
    features: list[FeatureOut]
    nav: list[NavItemOut]


@router.get("/me", response_model=MeOut)
async def me(ctx: RequestContext = Depends(get_request_context), session: AsyncSession = Depends(get_session)) -> MeOut:
    """Everything the web shell needs to decide what to show this user."""
    tenant = await session.get(Tenant, ctx.tenant_id)
    enabled = await enabled_feature_keys(session)
    features = load_features()
    return MeOut(
        tenant_id=tenant.id,
        tenant_name=tenant.name,
        clinic_type=tenant.clinic_type,
        tenant_status=tenant.status,
        role=ctx.role,
        features=[
            FeatureOut(
                key=f.key,
                name=f.name,
                description=f.description,
                enabled=f.available and f.key in enabled,
                available=f.available,
                accessible=can_use_feature(ctx.role, f.key),
                trial_eligible=f.trial_eligible,
                phi_sensitive=f.phi_sensitive,
            )
            for f in features.values()
        ],
        nav=[
            NavItemOut(feature=f.key, label=item.label, path=item.path)
            for f in features.values()
            if f.available and f.key in enabled and can_use_feature(ctx.role, f.key)
            for item in f.nav
            if not item.roles or ctx.role in item.roles
        ],
    )
