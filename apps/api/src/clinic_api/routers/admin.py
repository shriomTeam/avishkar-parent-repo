"""Tenant provisioning. Dev-only for now (mounted when APP_ENV=dev); becomes the
internal ops console / billing webhook later. Uses the RLS-bypassing system role."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from clinic_core.database import system_session
from clinic_core.entitlements import set_feature
from clinic_core.features import load_features
from clinic_db.models.core import ClinicType, Tenant, TenantStatus

router = APIRouter(prefix="/admin", tags=["admin (dev only)"])


class TenantIn(BaseModel):
    name: str
    clinic_type: ClinicType
    timezone: str = "America/New_York"
    features: list[str] = []
    trial_days: int | None = None  # lead-magnet trial: features expire
    baa_signed: bool = False
    settings: dict = {}


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    features: list[str]


@router.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(body: TenantIn) -> TenantOut:
    unknown = set(body.features) - set(load_features())
    if unknown:
        raise HTTPException(422, f"unknown features: {sorted(unknown)}")
    now = datetime.now(UTC)
    expires = now + timedelta(days=body.trial_days) if body.trial_days else None
    async with system_session() as s:
        tenant = Tenant(
            name=body.name,
            clinic_type=body.clinic_type,
            timezone=body.timezone,
            status=TenantStatus.TRIAL if body.trial_days else TenantStatus.ACTIVE,
            trial_ends_at=expires,
            baa_signed_at=now if body.baa_signed else None,
            settings=body.settings,
        )
        s.add(tenant)
        await s.flush()
        for key in body.features:
            await set_feature(s, tenant.id, key, expires_at=expires)
    return TenantOut(id=tenant.id, name=tenant.name, status=tenant.status, features=body.features)


class FeatureToggle(BaseModel):
    enabled: bool = True
    expires_at: datetime | None = None


@router.put("/tenants/{tenant_id}/features/{feature_key}")
async def toggle_feature(tenant_id: uuid.UUID, feature_key: str, body: FeatureToggle) -> dict:
    if feature_key not in load_features():
        raise HTTPException(404, "unknown feature")
    async with system_session() as s:
        await set_feature(s, tenant_id, feature_key, enabled=body.enabled, expires_at=body.expires_at)
    return {"tenant_id": tenant_id, "feature": feature_key, **body.model_dump()}
