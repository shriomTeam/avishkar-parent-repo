"""Fill a built-in tool's arguments from the details captured during the call.

The model already collected and confirmed those details with ``save_caller_details``, and the platform checked
them. Letting it type them again into a tool call risks a different spelling or a wrong digit, so an argument
that matches a captured field is taken from that field and hidden from the model.

Matching is decided once per call from the agent's fields (never from what the caller said):
1. a field whose key is the argument's name and whose type fits it;
2. otherwise, for phone and email only, the single field of that type.
Anything else stays with the model.
"""

from typing import Any

# What each argument of a built-in tool accepts: the field data type that can fill it.
ARG_TYPES = {"first_name": "text", "last_name": "text", "phone": "phone", "email": "email", "interest": "text"}
BY_TYPE = {"phone", "email"}  # arguments that may also be matched by type alone


def match_fields(schema: dict, fields: list[dict]) -> dict[str, dict[str, Any]]:
    """Return ``{argument: {"key", "label", "required"}}`` for the arguments the agent's fields can fill."""
    matched: dict[str, dict[str, Any]] = {}
    for arg in schema.get("properties", {}):
        wanted = ARG_TYPES.get(arg)
        if wanted is None:
            continue
        field = next((f for f in fields if f["key"] == arg and f["data_type"] == wanted), None)
        if field is None and arg in BY_TYPE:
            same_type = [f for f in fields if f["data_type"] == wanted]
            field = same_type[0] if len(same_type) == 1 else None
        if field is not None:
            matched[arg] = {"key": field["key"], "label": field["label"], "required": bool(field.get("required"))}
    return matched


def model_schema(schema: dict, filled: dict[str, Any]) -> dict:
    """The schema the model sees: filled arguments removed, so it cannot type them."""
    props = {name: node for name, node in schema.get("properties", {}).items() if name not in filled}
    out = {**schema, "properties": props}
    if "required" in schema:
        out["required"] = [r for r in schema["required"] if r in props]
    return out


def fill_args(args: dict[str, Any], filled: dict[str, Any], values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Add captured values to the model's ``args``. Returns (arguments, labels of required details still missing).
    A captured value always wins over anything the model sent; details that are not required are left out."""
    merged = dict(args)
    missing: list[str] = []
    for arg, source in filled.items():
        if source["key"] in values:
            merged[arg] = values[source["key"]]
        else:
            merged.pop(arg, None)
            if source["required"]:
                missing.append(source["label"])
    return merged, missing
