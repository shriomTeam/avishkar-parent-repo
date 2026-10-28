"""Reading and writing practice_settings rows. One immutable row per version; the highest version is current.

No row means version 0: the defaults in ``LeadResponseSettings``. The engine (a later chunk) reads settings at fire time
through ``current_settings``, so a timer always uses what the clinic saved last.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.lead_response import PracticeSettings
from clinic_lead_response.settings_model import LeadResponseSettings


async def current_row(session: AsyncSession) -> PracticeSettings | None:
    return await session.scalar(
        select(PracticeSettings)
        .where(PracticeSettings.tenant_id == current_tenant(session))
        .order_by(PracticeSettings.version.desc())
        .limit(1)
    )


def settings_from_row(row: PracticeSettings | None) -> LeadResponseSettings:
    if row is None:
        return LeadResponseSettings()
    return LeadResponseSettings.model_validate(
        {
            "ai_enabled": row.ai_enabled,
            "capabilities": row.capabilities,
            "send_mode": row.send_mode,
            "ai_active_mode": row.ai_active_mode,
            "overflow_minutes": row.overflow_minutes,
            "holding_minutes": row.holding_minutes,
            "sla_minutes": row.sla_minutes,
            "ack_text": row.ack_text,
            "business_hours": row.business_hours or {},
            "quiet_hours": row.quiet_hours or None,
            "escalation_role": row.escalation_role,
        }
    )


def columns_from_settings(settings: LeadResponseSettings) -> dict[str, Any]:
    """The column values for one row. ``ack_text`` is always included: the database has no default for it."""
    return {
        "ai_enabled": settings.ai_enabled,
        "capabilities": settings.capabilities.model_dump(),
        "send_mode": settings.send_mode,
        "ai_active_mode": settings.ai_active_mode,
        "overflow_minutes": settings.overflow_minutes,
        "holding_minutes": settings.holding_minutes,
        "sla_minutes": settings.sla_minutes,
        "ack_text": settings.ack_text,
        "business_hours": settings.business_hours.stored(),
        "quiet_hours": settings.quiet_hours.model_dump() if settings.quiet_hours else {},
        "escalation_role": settings.escalation_role,
    }


async def current_settings(session: AsyncSession) -> tuple[int, LeadResponseSettings]:
    row = await current_row(session)
    return (row.version if row else 0), settings_from_row(row)
