"""Audit a settings change with setting names only. Values can be wording or hours a clinic typed, so they stay out."""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.audit import audit

# Everything on a practice_settings row except its identity and bookkeeping columns.
BOOKKEEPING = {"id", "tenant_id", "version", "created_at", "created_by"}


def changed_setting_names(before: Mapping[str, Any] | None, after: Mapping[str, Any]) -> list[str]:
    """Names of the settings that differ. ``before`` is None for the first version: every setting counts as changed."""
    names = (set(after) | set(before or {})) - BOOKKEEPING
    return sorted(name for name in names if before is None or before.get(name) != after.get(name))


async def audit_settings_saved(
    session: AsyncSession,
    *,
    actor_id: str | None,
    settings_id: uuid.UUID,
    from_version: int,
    to_version: int,
    before: Mapping[str, Any] | None,
    after: Mapping[str, Any],
) -> None:
    await audit(
        session,
        "lead_response.settings.saved",
        actor_type="staff",
        actor_id=actor_id,
        entity_type="lead_response_settings",
        entity_id=settings_id,
        details={
            "from_version": from_version,
            "to_version": to_version,
            "changed": changed_setting_names(before, after),
        },
    )
