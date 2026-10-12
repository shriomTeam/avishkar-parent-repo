"""Guess a mapping from a file's headers, so onboarding is "upload, review, confirm".

Keeps the lead-magnet promise ("little setup on their end"): most EMR exports use
one of these header spellings. Staff review the suggestion before importing.
"""

import re

from clinic_integrations.canonical import ENTITY_MODELS
from clinic_integrations.mapping import FieldSpec, MappingConfig

_SYNONYMS: dict[str, list[str]] = {
    "first_name": ["first name", "firstname", "fname", "given name", "first"],
    "last_name": ["last name", "lastname", "lname", "surname", "family name", "last"],
    "email": ["email", "email address", "e-mail", "client email", "patient email"],
    "phone": ["phone", "mobile", "cell", "mobile phone", "cell phone", "phone number", "primary phone"],
    "date_of_birth": ["dob", "date of birth", "birthdate", "birthday", "birth date"],
    "gender": ["gender", "sex"],
    "first_seen_at": ["created", "created at", "client since", "patient since", "first visit"],
    "sms_opt_in": ["sms opt in", "text opt in", "sms consent", "marketing sms"],
    "email_opt_in": ["email opt in", "email consent", "marketing email", "newsletter"],
    "patient_external_id": ["patient id", "client id", "customer id", "mrn"],
    "starts_at": ["start", "start time", "appointment date", "date", "start date", "scheduled at", "appt date"],
    "ends_at": ["end", "end time", "end date"],
    "status": ["status", "appointment status", "state"],
    "provider_name": ["provider", "provider name", "staff", "staff name", "practitioner", "injector"],
    "provider_external_id": ["provider id", "staff id"],
    "service_name": ["service", "service name", "treatment", "item", "item name", "product"],
    "service_category": ["category", "service category", "treatment category"],
    "service_external_id": ["service id", "item id"],
    "amount_cents": ["amount", "total", "price", "net", "net sales", "total paid", "revenue"],
    "occurred_at": ["date", "sale date", "transaction date", "paid at", "invoice date"],
    "kind": ["type", "sale type", "item type"],
    "appointment_external_id": ["appointment id", "visit id"],
    "name": ["name", "full name", "service", "provider"],
    "credentials": ["credentials", "title", "license"],
    "category": ["category"],
    "price_cents": ["price", "default price"],
    "duration_minutes": ["duration", "length", "minutes"],
}

# The row's own id depends on what the file contains.
_EXTERNAL_ID: dict[str, list[str]] = {
    "patient": ["id", "patient id", "client id", "customer id", "record id", "mrn", "chart number"],
    "appointment": ["id", "appointment id", "visit id", "booking id"],
    "transaction": ["id", "transaction id", "invoice id", "sale id", "receipt id"],
    "provider": ["id", "provider id", "staff id"],
    "service": ["id", "service id", "item id"],
}

_TRANSFORMS = {
    "email": "lower",
    "phone": "phone_e164",
    "date_of_birth": "date",
    "first_seen_at": "datetime",
    "starts_at": "datetime",
    "ends_at": "datetime",
    "occurred_at": "datetime",
    "amount_cents": "money_cents",
    "price_cents": "money_cents",
    "duration_minutes": "int",
    "sms_opt_in": "bool",
    "email_opt_in": "bool",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def suggest_mapping(entity_type: str, headers: list[str]) -> MappingConfig:
    model = ENTITY_MODELS[entity_type]
    by_norm = {_norm(h): h for h in headers}
    taken: set[str] = set()
    fields: dict[str, str | FieldSpec] = {}
    for field in model.model_fields:
        synonyms = _EXTERNAL_ID[entity_type] if field == "external_id" else _SYNONYMS.get(field, [])
        for candidate in [field.replace("_", " "), *synonyms]:
            header = by_norm.get(_norm(candidate))
            if header and header not in taken:
                taken.add(header)
                transform = _TRANSFORMS.get(field)
                fields[field] = FieldSpec(column=header, transform=transform) if transform else header
                break
    # A single "Name" / "Full Name" column for patients: split it.
    if entity_type == "patient" and "first_name" not in fields:
        full = by_norm.get("name") or by_norm.get("full name") or by_norm.get("patient name")
        if full:
            fields["first_name"] = FieldSpec(column=full, transform="first_name")
            fields["last_name"] = FieldSpec(column=full, transform="last_name")
    return MappingConfig(fields=fields)
