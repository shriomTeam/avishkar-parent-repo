"""Payload templates for custom tools: what to send to the clinic's system, and where each value comes from.

A template is a JSON object (the request body, or the query for a GET) whose text values may hold placeholders,
and the endpoint's path and query may hold them too:

* ``{{field.phone}}``: a detail captured during the call and already checked. The model never types it.
* ``{{arg.reason}}``: something the model supplies; only these appear in the model's argument list.
* ``{{call.id}}``, ``{{call.caller_number}}``: facts about the call.

Everything else is a constant. The template is parsed as JSON first and values are put in afterwards, so a value can
never break the structure of the request. A text value that is exactly one placeholder keeps the value's type (a
number stays a number); inside longer text it is written as text. In the endpoint a value is URL-encoded, and
placeholders are refused in the host, so the address a tool calls can never be changed by a caller.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

PLACEHOLDER = re.compile(r"\{\{\s*(field|arg|call)\.([A-Za-z_][A-Za-z0-9_]{0,63})\s*\}\}")
CALL_NAMES = {"id", "caller_number"}
MAX_TEMPLATE_CHARS = 4_000
MAX_DEPTH = 4
MAX_ENDPOINT = 2_048


class TemplateError(ValueError):
    """The template is not valid. The message is shown to staff."""


@dataclass
class Used:
    fields: set[str] = field(default_factory=set)
    args: set[str] = field(default_factory=set)
    call: set[str] = field(default_factory=set)


def _scan(text: str, used: Used) -> None:
    for kind, name in PLACEHOLDER.findall(text):
        {"field": used.fields, "arg": used.args, "call": used.call}[kind].add(name)
    rest = PLACEHOLDER.sub("", text)
    if "{{" in rest or "}}" in rest:
        raise TemplateError(
            f'"{text[:60]}" has a double brace that is not a placeholder. '
            "Write {{field.name}}, {{arg.name}} or {{call.id}}."
        )


def _walk(node: Any, used: Used, depth: int = 1) -> None:
    if depth > MAX_DEPTH:
        raise TemplateError(f"The template is nested deeper than {MAX_DEPTH} levels.")
    if isinstance(node, dict):
        for key, value in node.items():
            if "{{" in key:
                raise TemplateError("Placeholders can only be used in values, not in names.")
            _walk(value, used, depth + 1)
    elif isinstance(node, list):
        for value in node:
            _walk(value, used, depth + 1)
    elif isinstance(node, str):
        _scan(node, used)


def endpoint_parts(endpoint: str) -> tuple[str, str]:
    """Split the endpoint into (the part up to the end of the host, the rest)."""
    scheme_end = endpoint.find("://") + 3 if "://" in endpoint else 0
    for index in range(scheme_end, len(endpoint)):
        if endpoint[index] in "/?#":
            return endpoint[:index], endpoint[index:]
    return endpoint, ""


def inspect(template: Any, endpoint: str | None) -> Used:
    """Check the template and endpoint, and report which placeholders they use. Raises TemplateError."""
    used = Used()
    if template is not None:
        if not isinstance(template, dict):
            raise TemplateError("The payload template must be a JSON object.")
        if len(json.dumps(template)) > MAX_TEMPLATE_CHARS:
            raise TemplateError(f"The payload template is longer than {MAX_TEMPLATE_CHARS} characters.")
        _walk(template, used)
    if endpoint:
        origin, rest = endpoint_parts(endpoint)
        if "{{" in origin or "}}" in origin:
            raise TemplateError("The host name cannot contain placeholders. Use them in the path or the query.")
        _scan(rest, used)
    unknown = used.call - CALL_NAMES
    if unknown:
        raise TemplateError(f"Unknown call detail {sorted(unknown)[0]}. Use one of: {', '.join(sorted(CALL_NAMES))}.")
    return used


def sample_endpoint(endpoint: str) -> str:
    """The endpoint with every placeholder replaced by a harmless word, to check its shape."""
    return PLACEHOLDER.sub("x", endpoint)


@dataclass
class Rendered:
    body: dict[str, Any] | None = None
    endpoint: str | None = None
    missing_args: list[str] = field(default_factory=list)


class _Dropped:
    """A key whose only value was an argument the model left out."""


_DROP = _Dropped()


def _lookup(kind: str, name: str, fields: dict[str, Any], args: dict[str, Any], call: dict[str, Any]) -> Any:
    source = {"field": fields, "arg": args, "call": call}[kind]
    return source.get(name)


def _text(value: Any) -> str:
    return "true" if value is True else "false" if value is False else "" if value is None else str(value)


def _render(node: Any, fields: dict, args: dict, call: dict) -> Any:
    if isinstance(node, dict):
        out = {k: _render(v, fields, args, call) for k, v in node.items()}
        return {k: v for k, v in out.items() if v is not _DROP}
    if isinstance(node, list):
        return [v for v in (_render(v, fields, args, call) for v in node) if v is not _DROP]
    if not isinstance(node, str):
        return node
    whole = PLACEHOLDER.fullmatch(node.strip())
    if whole:
        value = _lookup(whole.group(1), whole.group(2), fields, args, call)
        return _DROP if value is None else value
    return PLACEHOLDER.sub(lambda m: _text(_lookup(m.group(1), m.group(2), fields, args, call)), node)


def render(
    template: dict | None, endpoint: str, *, fields: dict[str, Any], args: dict[str, Any], call: dict[str, Any]
) -> Rendered:
    """Build the request. Arguments a URL needs but the model did not give are listed in ``missing_args``."""
    result = Rendered()
    origin, rest = endpoint_parts(endpoint)
    missing: list[str] = []

    def put(match: re.Match) -> str:
        value = _lookup(match.group(1), match.group(2), fields, args, call)
        if value is None:
            if match.group(1) == "arg":
                missing.append(match.group(2))
            return ""
        return quote(_text(value), safe="")

    result.endpoint = origin + PLACEHOLDER.sub(put, rest)
    result.missing_args = sorted(set(missing))
    if template is not None:
        result.body = _render(template, fields, args, call)
    return result


def model_schema(schema: dict, used: Used) -> dict:
    """The arguments the model is asked for: only those the template uses."""
    props = {name: node for name, node in schema.get("properties", {}).items() if name in used.args}
    out = {**schema, "properties": props}
    if "required" in schema:
        out["required"] = [r for r in schema["required"] if r in props]
    return out
