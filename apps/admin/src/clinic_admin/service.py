"""What the operator can read and change. Runs as the clinic_system role, so row-level security does not apply:
every query here names the clinic it means, and every change writes an audit line for that clinic."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.features import load_features
from clinic_db.models.core import Lead, Patient, Staff, Tenant, TenantFeature, TenantStatus
from clinic_db.models.ops import AuditLog
from clinic_db.models.voice import Call

STATUSES = tuple(status.value for status in TenantStatus)
ADMIN_ACTOR = "admin"


class AdminError(Exception):
    """A request the operator can fix: shown on the page, never a crash."""


@dataclass(frozen=True)
class FeatureInfo:
    key: str
    name: str
    description: str
    available: bool


def feature_catalog() -> dict[str, FeatureInfo]:
    """The features installed in this deployment. An entitlement for any other key is refused."""
    return {
        key: FeatureInfo(key, feature.name, feature.description, feature.available)
        for key, feature in load_features().items()
    }


def _is_active(row: TenantFeature, now: datetime) -> bool:
    return row.enabled and (row.expires_at is None or row.expires_at > now)


async def list_clinics(session: AsyncSession, *, query: str = "", status: str = "", limit: int = 200) -> list[dict]:
    now = datetime.now(UTC)
    staff_count = select(func.count()).where(Staff.tenant_id == Tenant.id, Staff.active.is_(True)).scalar_subquery()
    feature_count = (
        select(func.count())
        .where(
            TenantFeature.tenant_id == Tenant.id,
            TenantFeature.enabled.is_(True),
            or_(TenantFeature.expires_at.is_(None), TenantFeature.expires_at > now),
        )
        .scalar_subquery()
    )
    stmt = select(Tenant, staff_count.label("staff"), feature_count.label("features")).order_by(
        Tenant.created_at.desc()
    )
    if query.strip():
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Tenant.name.ilike(f"%{escaped}%", escape="\\"))
    if status in STATUSES:
        stmt = stmt.where(Tenant.status == status)
    rows = (await session.execute(stmt.limit(limit))).all()
    return [{"tenant": tenant, "staff": staff, "features": features} for tenant, staff, features in rows]


async def dashboard(session: AsyncSession) -> dict:
    now = datetime.now(UTC)
    by_status = dict((await session.execute(select(Tenant.status, func.count()).group_by(Tenant.status))).all())
    rows = (
        await session.execute(
            select(TenantFeature.feature_key, func.count())
            .where(
                TenantFeature.enabled.is_(True),
                or_(TenantFeature.expires_at.is_(None), TenantFeature.expires_at > now),
            )
            .group_by(TenantFeature.feature_key)
        )
    ).all()
    return {"by_status": by_status, "total": sum(by_status.values()), "feature_clinics": dict(rows)}


async def clinic_detail(session: AsyncSession, tenant_id: uuid.UUID) -> dict | None:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        return None
    now = datetime.now(UTC)
    feature_rows = {
        row.feature_key: row
        for row in await session.scalars(select(TenantFeature).where(TenantFeature.tenant_id == tenant_id))
    }
    staff = list(await session.scalars(select(Staff).where(Staff.tenant_id == tenant_id).order_by(Staff.name)))

    async def count(model) -> int:
        return await session.scalar(select(func.count()).select_from(model).where(model.tenant_id == tenant_id)) or 0

    return {
        "tenant": tenant,
        "features": feature_rows,
        "active_keys": {key for key, row in feature_rows.items() if _is_active(row, now)},
        "staff": staff,
        "counts": {"Patients": await count(Patient), "Leads": await count(Lead), "Voice calls": await count(Call)},
        "audit": await recent_actions(session, tenant_id=tenant_id, limit=20),
    }


def _record(session: AsyncSession, tenant_id: uuid.UUID, action: str, username: str, details: dict) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_type=ADMIN_ACTOR,
            actor_id=username,
            action=action,
            entity_type="tenant",
            entity_id=tenant_id,
            details=details,
        )
    )


async def set_feature_state(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    key: str,
    *,
    enabled: bool,
    expires_at: datetime | None,
    username: str,
) -> None:
    if key not in feature_catalog():
        raise AdminError(f"“{key}” is not a feature installed in this deployment.")
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise AdminError("The end date must be in the future.")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise AdminError("That clinic does not exist.")
    row = await session.get(TenantFeature, (key, tenant_id))
    if row is None:
        session.add(
            TenantFeature(feature_key=key, tenant_id=tenant_id, enabled=enabled, expires_at=expires_at, config={})
        )
    else:
        # Only the switch and the end date change: the clinic's feature settings in `config` stay as they are.
        row.enabled = enabled
        row.expires_at = expires_at
    _record(
        session,
        tenant_id,
        "admin.feature.enabled" if enabled else "admin.feature.disabled",
        username,
        {"feature": key, "expires_at": expires_at.isoformat() if expires_at else None},
    )


async def set_status(session: AsyncSession, tenant_id: uuid.UUID, status: str, *, username: str) -> None:
    if status not in STATUSES:
        raise AdminError("Unknown status.")
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise AdminError("That clinic does not exist.")
    if tenant.status == status:
        return
    previous, tenant.status = tenant.status, status
    _record(session, tenant_id, "admin.tenant.status_changed", username, {"from": previous, "to": status})


async def recent_actions(session: AsyncSession, *, tenant_id: uuid.UUID | None = None, limit: int = 100) -> list[dict]:
    stmt = (
        select(AuditLog, Tenant.name)
        .join(Tenant, Tenant.id == AuditLog.tenant_id)
        .where(AuditLog.actor_type == ADMIN_ACTOR)
        .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    if tenant_id:
        stmt = stmt.where(AuditLog.tenant_id == tenant_id)
    return [{"entry": entry, "clinic": name} for entry, name in (await session.execute(stmt)).all()]
