"""Variables: fixed values a clinic writes into agent prompts as ``{{name}}``.

Two kinds. The clinic's own variables are plain text it defines once and every agent can use (the clinic's
opening hours, its address). Built-in variables are filled in by the platform at the start of each call (the
date, the caller's number). Details the agent captures during a call are not variables: they only exist after
the caller has spoken, so a prompt cannot use them.

A call stores the prompt with every variable already filled in, so its record shows what the agent was given.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.voice import Agent, Variable

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
# Any identifier-looking word between double braces, so a typo such as {{Clinic_Name}} is caught instead of
# being spoken to a caller as literal text.
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
MAX_VALUE_LENGTH = 1000
MAX_VARIABLES = 100


@dataclass(frozen=True)
class Builtin:
    name: str
    description: str
    example: str


BUILTINS: tuple[Builtin, ...] = (
    Builtin("agent_name", "The name of the agent taking the call.", "Front desk"),
    Builtin("clinic_name", "Your workspace name.", "Glow Aesthetics"),
    Builtin("caller_number", "The number the caller is phoning from. Not available in a browser test.", "+14155550123"),
    Builtin("current_date", "Today's date at your clinic.", "Thursday, 22 October 2026"),
    Builtin("current_time", "The time now at your clinic.", "3:05 PM"),
)
BUILTIN_NAMES = frozenset(b.name for b in BUILTINS)


class VariableError(Exception):
    pass


class NameTaken(VariableError):
    pass


class InUse(VariableError):
    def __init__(self, agents: list[str]):
        super().__init__(", ".join(agents))
        self.agents = agents


def placeholders(*texts: str | None) -> list[str]:
    """The distinct variable names used in the given texts, in order of first appearance."""
    found: dict[str, None] = {}
    for text in texts:
        for name in PLACEHOLDER.findall(text or ""):
            found.setdefault(name, None)
    return list(found)


def resolve(text: str | None, values: dict[str, str]) -> str | None:
    """Fill in known variables in one pass, so a value that itself contains braces is never expanded again."""
    if text is None:
        return None
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def builtin_values(
    *, agent_name: str, clinic_name: str, timezone: str, caller_number: str | None, now: datetime
) -> dict[str, str]:
    try:
        local = now.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        local = now
    return {
        "agent_name": agent_name,
        "clinic_name": clinic_name,
        "caller_number": caller_number or "not available",
        "current_date": f"{local:%A}, {local.day} {local:%B %Y}",
        "current_time": f"{local.hour % 12 or 12}:{local:%M} {'AM' if local.hour < 12 else 'PM'}",
    }


async def list_variables(session: AsyncSession) -> list[Variable]:
    return list((await session.scalars(select(Variable).order_by(Variable.name))).all())


async def custom_values(session: AsyncSession) -> dict[str, str]:
    return {v.name: v.value for v in await list_variables(session)}


async def unknown_names(session: AsyncSession, *texts: str | None) -> list[str]:
    """Names used in the texts that are neither built in nor defined by the clinic."""
    used = placeholders(*texts)
    if not used:
        return []
    known = BUILTIN_NAMES | set(await custom_values(session))
    return [name for name in used if name not in known]


async def usage(session: AsyncSession) -> dict[str, list[str]]:
    """For each variable name, the names of the agents whose prompt or first message uses it."""
    out: dict[str, list[str]] = {}
    for name, prompt, greeting in (await session.execute(select(Agent.name, Agent.prompt, Agent.greeting))).all():
        for variable in placeholders(prompt, greeting):
            out.setdefault(variable, []).append(name)
    return out


async def create(session: AsyncSession, *, tenant_id: uuid.UUID, name: str, value: str) -> Variable:
    if name in BUILTIN_NAMES:
        raise NameTaken(f"{name} is built in. Choose another name.")
    if len(await list_variables(session)) >= MAX_VARIABLES:
        raise VariableError(f"A clinic can have up to {MAX_VARIABLES} variables.")
    variable = Variable(tenant_id=tenant_id, name=name, value=value)
    try:
        async with session.begin_nested():
            session.add(variable)
            await session.flush()
    except IntegrityError:
        raise NameTaken("A variable with this name already exists.") from None
    return variable


async def delete(session: AsyncSession, variable: Variable) -> None:
    agents = (await usage(session)).get(variable.name, [])
    if agents:
        raise InUse(agents)
    await session.delete(variable)
