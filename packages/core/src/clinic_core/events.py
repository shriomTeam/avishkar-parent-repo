"""Domain events: the only way features react to each other.

Write with ``emit`` inside the same transaction as the change. The worker relays
the outbox to every enabled feature's ``event_handlers``. Adding an event type
here is a cross-team contract change: keep payloads small (ids, not whole rows).
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.database import current_tenant
from clinic_db.models.ops import OutboxEvent

# Well-known event types and their payloads.
PATIENT_CREATED = "patient.created"  # {patient_id}
LEAD_CREATED = "lead.created"  # {lead_id, channel}
APPOINTMENT_BOOKED = "appointment.booked"  # {appointment_id, patient_id, booked_via}
APPOINTMENT_COMPLETED = "appointment.completed"  # {appointment_id, patient_id}
APPOINTMENT_CANCELLED = "appointment.cancelled"  # {appointment_id, patient_id}
MESSAGE_INBOUND = "message.inbound"  # {patient_id?, lead_id?, channel, body}
CONSENT_CHANGED = "consent.changed"  # {patient_id, kind, granted}
IMPORT_COMPLETED = "import.completed"  # {batch_id, entity_type, stats}


async def emit(session: AsyncSession, event_type: str, payload: dict[str, Any]) -> None:
    session.add(OutboxEvent(tenant_id=current_tenant(session), event_type=event_type, payload=payload))
