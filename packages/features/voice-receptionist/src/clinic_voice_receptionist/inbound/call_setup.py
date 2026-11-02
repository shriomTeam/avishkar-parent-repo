"""What every new call needs before it starts: stale calls closed, and the agent's settings frozen into a snapshot.

Shared by browser test calls and phone calls, so both give the model exactly the same thing.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.core import Tenant
from clinic_db.models.voice import Agent, Call
from clinic_voice_receptionist.config import VoiceSettings
from clinic_voice_receptionist.inbound import service
from clinic_voice_receptionist.inbound.live import tickets
from clinic_voice_receptionist.tools import fill, template
from clinic_voice_receptionist.tools.service import refresh_builtins
from clinic_voice_receptionist.variables import service as variables


async def expire_stale_calls(session: AsyncSession, voice: VoiceSettings, now: datetime) -> None:
    """Calls that were never opened, or outlived the call limit (for example after a restart), are over."""
    await session.execute(
        update(Call)
        .where(
            Call.status.in_(("connecting", "in_progress")),
            ((Call.status == "connecting") & (Call.started_at < now - tickets.TICKET_TTL))
            | (Call.started_at < now - timedelta(seconds=voice.max_call_seconds + 60)),
        )
        .values(status="failed", end_reason="expired", ended_at=now)
    )


async def build_snapshot(
    session: AsyncSession, agent: Agent, tenant_id: uuid.UUID, *, caller_number: str | None, now: datetime
) -> dict:
    fields = await service.agent_fields(session, agent.id)
    await refresh_builtins(session)  # a call always gets the current wording of built-in tools
    tools = await service.attached_tools(session, agent.id)
    # Variables are filled in once, when the call starts, so the call keeps exactly what the agent was told.
    tenant = await session.get(Tenant, tenant_id)
    values = (await variables.custom_values(session)) | variables.builtin_values(
        agent_name=agent.name,
        clinic_name=tenant.name if tenant else "",
        timezone=tenant.timezone if tenant else "UTC",
        caller_number=caller_number,
        now=now,
    )
    field_entries = [
        {
            "id": str(f.id),
            "key": f.key,
            "label": f.label,
            "description": f.description,
            "data_type": f.data_type,
            "enum_values": f.enum_values,
            "required": f.required,
        }
        for f in fields
    ]
    return {
        "id": str(agent.id),
        "name": agent.name,
        "prompt": variables.resolve(agent.prompt, values),
        "greeting": variables.resolve(agent.greeting, values),
        "voice": agent.voice,
        "language": agent.language,
        "speech_start_sensitivity": agent.speech_start_sensitivity,
        "model": agent.model,
        "save_transcript": agent.save_transcript,
        "save_raw_events": agent.save_raw_events,
        "save_recording": agent.save_recording,
        # Only what the model needs. Endpoints and auth headers stay out of the call record; the runner reads them
        # fresh when a tool runs, so disabling or deleting a tool takes effect even mid-call.
        "tools": [_tool_entry(t, field_entries) for t in tools],
        "fields": field_entries,
    }


def _tool_entry(tool, fields: list[dict]) -> dict:
    """What the call keeps of a tool. A built-in's arguments that the agent's fields can fill are taken out of
    the schema the model sees and listed in ``filled``; the runner adds the captured values when it runs."""
    filled = fill.match_fields(tool.input_schema, fields) if tool.kind == "builtin" else {}
    schema = fill.model_schema(tool.input_schema, filled)
    if tool.kind == "http" and tool.payload_template is not None:
        # The model is only asked for what the template uses; captured details never appear in its argument list.
        schema = template.model_schema(tool.input_schema, template.inspect(tool.payload_template, tool.endpoint))
    description = tool.description
    if filled:
        names = ", ".join(sorted(filled))
        description += (
            f" These details are added automatically from what you saved with save_caller_details, so do not "
            f"send them yourself: {names}."
        )
    return {
        "id": str(tool.id),
        "name": tool.name,
        "description": description,
        "kind": tool.kind,
        "schema": schema,
        "filled": filled,
        "labels": {f["key"]: f["label"] for f in fields} if tool.kind == "http" else {},
        "timeout_seconds": tool.timeout_seconds,
    }
