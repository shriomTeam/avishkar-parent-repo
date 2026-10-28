import uuid

from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.voice import AgentField, Tool
from clinic_voice_receptionist.config import get_voice_settings
from clinic_voice_receptionist.inbound.live.prompt import END_TOOL, SAVE_TOOL
from clinic_voice_receptionist.inbound.schemas import ToolIn, ToolOut
from clinic_voice_receptionist.tools import secrets, template
from clinic_voice_receptionist.tools.builtin import BUILTINS
from clinic_voice_receptionist.tools.http_tool import check_header_name
from clinic_voice_receptionist.tools.netguard import BlockedTarget, parse_url
from clinic_voice_receptionist.tools.schema import SchemaError, validate_definition

RESERVED_NAMES = {SAVE_TOOL, END_TOOL, *BUILTINS}


class ToolError(Exception):
    """A tool definition problem; the message is shown to staff as is."""


class ToolNameTaken(ToolError):
    pass


def tool_out(tool: Tool) -> ToolOut:
    builtin = BUILTINS.get(tool.builtin_key or "")
    return ToolOut.model_validate(tool, from_attributes=True).model_copy(
        update={
            "has_auth": bool(tool.auth_header_secret),
            "default_description": builtin.description if builtin else None,
        }
    )


async def refresh_builtins(session: AsyncSession) -> None:
    """Built-in tools a clinic has added follow the platform's wording and schema, unless the clinic wrote its own
    description. Never adds a tool: clinics choose which ones they use."""
    for builtin in BUILTINS.values():
        await session.execute(
            update(Tool)
            .where(Tool.kind == "builtin", Tool.builtin_key == builtin.name)
            .values(
                description=case((Tool.description_customized.is_(True), Tool.description), else_=builtin.description),
                input_schema=builtin.schema,
            )
        )


async def add_builtin(session: AsyncSession, tenant_id: uuid.UUID, key: str) -> Tool:
    builtin = BUILTINS.get(key)
    if builtin is None:
        raise ToolError("Choose one of the internal tools in the list.")
    if await session.scalar(select(Tool.id).where(Tool.builtin_key == key)):
        raise ToolNameTaken(f"{builtin.title} is already added.")
    tool = Tool(
        tenant_id=tenant_id,
        name=builtin.name,
        description=builtin.description,
        kind="builtin",
        builtin_key=builtin.name,
        method="POST",
        timeout_seconds=5,
        input_schema=builtin.schema,
        enabled=True,
    )
    session.add(tool)
    try:
        await session.flush()
    except IntegrityError:  # a custom tool already uses the name
        raise ToolNameTaken(f'A tool named "{builtin.name}" already exists. Rename or delete it first.') from None
    await session.refresh(tool)
    return tool


async def catalog(session: AsyncSession) -> list[dict]:
    added = set((await session.scalars(select(Tool.builtin_key).where(Tool.kind == "builtin"))).all())
    return [
        {"key": b.name, "title": b.title, "description": b.description, "added": b.name in added}
        for b in BUILTINS.values()
    ]


async def list_tools(session: AsyncSession) -> list[Tool]:
    await refresh_builtins(session)
    return list((await session.scalars(select(Tool).order_by(Tool.kind, Tool.name))).all())


def _validate(body: ToolIn, existing: Tool | None) -> template.Used:
    if body.name in RESERVED_NAMES:
        raise ToolError(f'"{body.name}" is used by the platform. Choose another name.')
    if not body.description.strip():
        raise ToolError("Describe when the agent should use this tool.")
    if not body.endpoint:
        raise ToolError("Enter the HTTPS endpoint to call.")
    try:
        used = template.inspect(body.payload_template, body.endpoint)
        allow_private = get_voice_settings().tool_allow_private_hosts
        parse_url(template.sample_endpoint(body.endpoint.strip()), allow_private=allow_private)
        validate_definition(body.input_schema)
        if body.auth_header_name:
            check_header_name(body.auth_header_name)
    except (BlockedTarget, SchemaError, template.TemplateError) as exc:
        raise ToolError(str(exc)) from None
    unknown_args = used.args - set(body.input_schema["properties"])
    if unknown_args:
        name = sorted(unknown_args)[0]
        raise ToolError(f"The template uses {{{{arg.{name}}}}}, but the input schema has no argument by that name.")
    if body.method == "GET" and any(isinstance(v, (dict, list)) for v in (body.payload_template or {}).values()):
        raise ToolError("For a GET request the template can only hold single values, not lists or objects.")
    has_secret = bool(existing and existing.auth_header_secret and not body.clear_auth)
    if body.auth_header_name and not (body.auth_header_value or has_secret):
        raise ToolError("Enter the value to send in the auth header.")
    if body.auth_header_value and any(ord(c) < 32 or ord(c) == 127 for c in body.auth_header_value):
        raise ToolError("The auth header value cannot contain line breaks or other control characters.")
    if body.auth_header_value and not body.auth_header_name:
        raise ToolError("Enter the auth header name, for example Authorization.")
    return used


async def save_tool(session: AsyncSession, *, tenant_id: uuid.UUID, body: ToolIn, tool: Tool | None = None) -> Tool:
    if tool is not None and tool.kind == "builtin":
        # Built-in tools are fixed apart from the on/off switch and the description (when and how to use it).
        wording = body.description.strip()
        default = BUILTINS[tool.builtin_key].description
        if not wording:
            raise ToolError("Describe when the agent should use this tool.")
        tool.enabled = body.enabled
        tool.description = wording
        tool.description_customized = wording != default
        await session.flush()
        await session.refresh(tool)
        return tool
    used = _validate(body, tool)
    known = set((await session.scalars(select(AgentField.key).distinct())).all())
    unknown_fields = used.fields - known
    if unknown_fields:
        raise ToolError(
            f'No agent captures a detail called "{sorted(unknown_fields)[0]}". '
            "Add it under the agent's What to capture first, or check the spelling."
        )
    taken = select(Tool.id).where(Tool.name == body.name)
    if tool is not None:
        taken = taken.where(Tool.id != tool.id)
    if await session.scalar(taken):
        raise ToolNameTaken("A tool with this name already exists.")
    values = {
        "name": body.name,
        "description": body.description.strip(),
        "endpoint": body.endpoint.strip(),
        "method": body.method,
        "timeout_seconds": body.timeout_seconds,
        "input_schema": body.input_schema,
        "payload_template": body.payload_template or None,
        "enabled": body.enabled,
        "auth_header_name": body.auth_header_name or None,
    }
    try:
        secret = secrets.encrypt(body.auth_header_value) if body.auth_header_value else None
    except secrets.SecretsUnavailable:
        raise ToolError("Secure storage for auth headers is not configured on this server.") from None
    if tool is None:
        tool = Tool(tenant_id=tenant_id, kind="http", auth_header_secret=secret, **values)
        session.add(tool)
    else:
        for name, value in values.items():
            setattr(tool, name, value)
        if body.clear_auth or not body.auth_header_name:
            tool.auth_header_secret = None
        elif secret:
            tool.auth_header_secret = secret
    await session.flush()
    await session.refresh(tool)
    return tool
