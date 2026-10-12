"""Booking is a platform capability: the voice agent, lead follow-up, reactivation
replies and staff all book through here, so ``appointment.booked`` is always emitted.

TODO: write-back to the clinic's EMR/scheduler once its connector exists.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session
from clinic_core.events import APPOINTMENT_BOOKED, emit
from clinic_db.models.core import Appointment, AppointmentStatus, Patient

router = APIRouter(prefix="/appointments", tags=["appointments"])


class BookIn(BaseModel):
    patient_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime | None = None
    provider_id: uuid.UUID | None = None
    service_id: uuid.UUID | None = None
    location_id: uuid.UUID | None = None
    booked_via: str = "staff"


class BookOut(BaseModel):
    id: uuid.UUID
    status: str


@router.post("", response_model=BookOut, status_code=201)
async def book(
    body: BookIn, ctx: RequestContext = Depends(get_request_context), session: AsyncSession = Depends(get_session)
) -> BookOut:
    if await session.get(Patient, body.patient_id) is None:
        raise HTTPException(404, "patient not found")
    appt = Appointment(tenant_id=ctx.tenant_id, status=AppointmentStatus.BOOKED, **body.model_dump())
    session.add(appt)
    await session.flush()
    await emit(
        session,
        APPOINTMENT_BOOKED,
        {"appointment_id": str(appt.id), "patient_id": str(appt.patient_id), "booked_via": appt.booked_via},
    )
    return BookOut(id=appt.id, status=appt.status)
