"""Run lifecycle. For now: the measured return rates a run uses instead of the assumed range."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_reactivation.analysis.revenue import MeasuredRate

# Contacted: distinct patients whose target was texted (contacted or booked). Pending targets were skipped
# at launch and opted-out targets asked to stop, so neither counts. Booked: distinct among them whose
# booking was recorded inside the attribution window after launch. Only campaigns created from a run type
# (type_key set, no free-form audience) whose window has fully elapsed feed a rate. "No audience" is SQL NULL
# or JSON null: SQLAlchemy stores an explicit Python None in a JSONB column as JSON null.
_MEASURED_SQL = text(
    """
SELECT c.type_key,
       count(DISTINCT t.patient_id) FILTER (WHERE t.status IN ('contacted', 'booked')) AS contacted,
       count(DISTINCT t.patient_id) FILTER (
         WHERE t.status = 'booked'
           AND t.booked_at >= c.launched_at
           AND t.booked_at <= c.launched_at + make_interval(days => CAST(:window AS integer))
       ) AS booked
FROM reactivation.campaigns c
JOIN reactivation.campaign_targets t ON t.campaign_id = c.id
WHERE c.tenant_id = :tenant_id AND t.tenant_id = :tenant_id
  AND c.type_key IS NOT NULL
  AND (c.audience IS NULL OR jsonb_typeof(c.audience) = 'null')
  AND c.launched_at IS NOT NULL
  AND c.launched_at + make_interval(days => CAST(:window AS integer)) <= CAST(:now AS timestamptz)
GROUP BY c.type_key
"""
)


async def load_measured_rates(session: AsyncSession, now: datetime, window_days: int) -> dict[str, MeasuredRate]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    rows = await session.execute(
        _MEASURED_SQL, {"now": now, "window": window_days, "tenant_id": current_tenant(session)}
    )
    return {
        row.type_key: MeasuredRate(booked=min(int(row.booked), int(row.contacted)), contacted=int(row.contacted))
        for row in rows
    }
