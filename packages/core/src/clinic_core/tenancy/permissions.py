"""Server-owned role grants. Unknown role/feature pairs are denied."""

from fastapi import HTTPException

MANAGERS = {"owner", "office_manager"}
MEMBER_ROLES = {"front_desk", "provider", "consultant"}


def grantable_roles(actor_role):
    return (
        sorted(MEMBER_ROLES | ({"office_manager"} if actor_role == "owner" else set()))
        if actor_role in MANAGERS
        else []
    )


def require_grant(actor_role, target_role):
    if target_role not in grantable_roles(actor_role):
        raise HTTPException(403, detail="role_grant_denied")


def can_use_feature(role, feature):
    return role in MANAGERS or (role == "front_desk" and feature in {"voice_receptionist", "reactivation"})


async def live_session_allowed(settings, session_id, tenant_id):
    """Revalidate session and management permission for long-lived privileged work."""
    from sqlalchemy import select

    from clinic_core.auth.security import now
    from clinic_core.database import system_session
    from clinic_db.models.auth import AuthSession, User
    from clinic_db.models.core import Staff, Tenant, TenantStatus

    if session_id is None:
        return settings.is_dev and settings.allow_dev_auth
    async with system_session(database_url=settings.database_system_url) as db:
        return bool(
            await db.scalar(
                select(AuthSession.user_id)
                .join(User, User.id == AuthSession.user_id)
                .join(Staff, Staff.user_id == User.id)
                .join(Tenant, Tenant.id == Staff.tenant_id)
                .where(
                    AuthSession.id == session_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now(),
                    AuthSession.active_workspace_id == tenant_id,
                    User.active.is_(True),
                    Staff.tenant_id == tenant_id,
                    Staff.active.is_(True),
                    Staff.role.in_(MANAGERS),
                    Tenant.status != TenantStatus.SUSPENDED,
                )
            )
        )
