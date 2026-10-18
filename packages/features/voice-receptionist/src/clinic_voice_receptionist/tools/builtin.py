"""Tools that run inside the platform, with no outbound request. A clinic adds them from a catalog."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_core.events import LEAD_CREATED, emit
from clinic_db.models.core import Lead
from clinic_db.models.voice import Call
from clinic_voice_receptionist.inbound.live.fields import InvalidValue, coerce


@dataclass(frozen=True)
class Builtin:
    name: str  # the function name the model calls, and the tool's name in the clinic
    title: str  # what the catalog shows
    description: str
    schema: dict


_LEAD_FIELDS = {
    "first_name": {"type": "string", "description": "Caller's first name"},
    "last_name": {"type": "string", "description": "Caller's last name"},
    "phone": {"type": "string", "description": "Phone number in E.164 format, for example +14155550123"},
    "email": {"type": "string", "description": "Email address"},
    "interest": {"type": "string", "description": "What the caller wants, in a few words"},
}

BUILTINS: dict[str, Builtin] = {
    "create_lead": Builtin(
        name="create_lead",
        title="Create lead",
        description=(
            "Send the caller to the clinic team as a lead so staff can follow up. Saving details with "
            "save_caller_details does NOT notify the team; this function does. Call it as soon as the caller has "
            "confirmed their name and a phone number or email, and always before you say goodbye. "
            "Calling it again updates the same lead."
        ),
        schema={"type": "object", "properties": _LEAD_FIELDS},
    ),
    "update_lead": Builtin(
        name="update_lead",
        title="Update lead",
        description=(
            "Change the details of the lead you already created during this call, when the caller gives new or "
            "corrected information afterwards. It never creates a lead: if none exists yet it reports that, "
            "and you should use create_lead first. Send only what changed."
        ),
        schema={"type": "object", "properties": _LEAD_FIELDS},
    ),
}


def _lead_values(args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, kind in (
        ("first_name", "text"),
        ("last_name", "text"),
        ("phone", "phone"),
        ("email", "email"),
        ("interest", "text"),
    ):
        if args.get(key) in (None, ""):
            continue
        try:
            values[key] = coerce({"data_type": kind}, args[key])
        except InvalidValue as exc:
            errors[key] = str(exc)
    return values, errors


async def run_lead(
    *, tenant_id: uuid.UUID, call_id: uuid.UUID, args: dict[str, Any], database_url: str | None, create: bool
) -> dict[str, Any]:
    """Save the caller as a lead linked to the call. ``create`` makes one if needed; otherwise only updates.
    Either way a call only ever has one lead, and only that lead can be changed from a call."""
    values, errors = _lead_values(args)
    if errors:
        return {"ok": False, "invalid": errors}
    if create and not (values.get("phone") or values.get("email")):
        return {"ok": False, "error": "A phone number or an email is needed to create a lead."}
    if not create and not values:
        return {"ok": False, "error": "Nothing to update. Send at least one detail that changed."}
    async with tenant_session(tenant_id, database_url=database_url) as session:
        call = await session.scalar(select(Call).where(Call.id == call_id).with_for_update())
        if call is None:
            return {"ok": False, "error": "This call no longer exists."}
        lead = await session.get(Lead, call.lead_id) if call.lead_id else None
        if lead is None and not create:
            return {"ok": False, "error": "There is no lead for this call yet. Use create_lead first."}
        created = lead is None
        if lead is None:
            lead = Lead(
                tenant_id=tenant_id,
                channel="call",
                status="new",
                utm={"source": "voice_agent", "call_id": str(call_id)},
            )
            session.add(lead)
        for key, value in values.items():
            setattr(lead, key, value)
        await session.flush()
        call.lead_id = lead.id
        if created:
            await emit(session, LEAD_CREATED, {"lead_id": str(lead.id), "channel": "call"})
        return {"ok": True, "lead_id": str(lead.id), "created": created}
