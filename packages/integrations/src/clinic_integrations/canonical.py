"""Canonical import shapes. Every source, whatever its format, is mapped into these.

References between entities use the *source system's* ids (``patient_external_id``)
or names (``service_name``); the loader resolves them to our UUIDs.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from clinic_db.models.core import AppointmentStatus


class PatientIn(BaseModel):
    external_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    date_of_birth: date | None = None
    gender: str | None = None
    first_seen_at: datetime | None = None
    sms_opt_in: bool | None = None
    email_opt_in: bool | None = None

    @field_validator("email", mode="before")
    @classmethod
    def _email_lower(cls, v):
        return v.strip().lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _identifiable(self):
        if not (self.external_id or self.email or self.phone):
            raise ValueError("patient needs external_id, email or phone")
        return self


class ProviderIn(BaseModel):
    external_id: str | None = None
    name: str
    credentials: str | None = None


class ServiceIn(BaseModel):
    external_id: str | None = None
    name: str
    category: str | None = None
    price_cents: int | None = None
    duration_minutes: int | None = None


# How EMRs commonly spell appointment states. A mapping's value_map can override.
_STATUS_SYNONYMS = {
    **dict.fromkeys(
        ["checked out", "complete", "completed", "arrived", "paid", "closed", "finished", "show"],
        AppointmentStatus.COMPLETED,
    ),
    **dict.fromkeys(
        ["confirmed", "scheduled", "booked", "pending", "unconfirmed", "requested"], AppointmentStatus.BOOKED
    ),
    **dict.fromkeys(
        ["canceled", "cancelled", "late cancel", "late cancellation", "rescheduled"], AppointmentStatus.CANCELLED
    ),
    **dict.fromkeys(["no show", "noshow", "missed", "did not show"], AppointmentStatus.NO_SHOW),
}


class AppointmentIn(BaseModel):
    external_id: str | None = None
    patient_external_id: str
    starts_at: datetime
    ends_at: datetime | None = None
    status: AppointmentStatus = AppointmentStatus.BOOKED
    provider_external_id: str | None = None
    provider_name: str | None = None
    service_external_id: str | None = None
    service_name: str | None = None
    service_category: str | None = None

    @field_validator("status", mode="before")
    @classmethod
    def _status(cls, v):
        if not v:
            return AppointmentStatus.BOOKED
        s = str(v).strip().lower().replace("-", " ").replace("_", " ")
        return _STATUS_SYNONYMS.get(s, s.replace(" ", "_"))


class TransactionIn(BaseModel):
    external_id: str | None = None
    patient_external_id: str | None = None
    appointment_external_id: str | None = None
    amount_cents: int
    occurred_at: datetime
    kind: Literal["service", "product", "membership", "package", "refund", "other"] = "service"
    service_name: str | None = None
    service_category: str | None = None
    provider_name: str | None = None


ENTITY_MODELS: dict[str, type[BaseModel]] = {
    "patient": PatientIn,
    "provider": ProviderIn,
    "service": ServiceIn,
    "appointment": AppointmentIn,
    "transaction": TransactionIn,
}

# Order to import a full export in, so references resolve.
IMPORT_ORDER = ["provider", "service", "patient", "appointment", "transaction"]
