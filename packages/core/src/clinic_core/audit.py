import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.ops import AuditLog


async def audit(
    session: AsyncSession,
    action: str,
    *,
    actor_type: str,
    actor_id: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Record access to or changes of PHI. Append-only (the app role cannot update/delete)."""
    session.add(
        AuditLog(
            tenant_id=current_tenant(session),
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details or {},
        )
    )
