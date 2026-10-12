"""Dev-only helpers to exercise flows without real phones (mounted when APP_ENV=dev)."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import get_session
from clinic_core.events import MESSAGE_INBOUND, emit

router = APIRouter(prefix="/dev", tags=["dev"])


class InboundIn(BaseModel):
    patient_id: uuid.UUID
    body: str
    channel: str = "sms"


@router.post("/inbound-message")
async def inbound(body: InboundIn, session: AsyncSession = Depends(get_session)) -> dict:
    """Pretend a patient texted back (e.g. "STOP" or "yes please")."""
    await emit(
        session, MESSAGE_INBOUND, {"patient_id": str(body.patient_id), "body": body.body, "channel": body.channel}
    )
    return {"queued": True}
