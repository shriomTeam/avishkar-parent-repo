"""The small slice of JSON Schema that tools use.

Gemini's function calling accepts a subset of JSON Schema, so we accept the same subset when a tool is saved,
check the model's arguments against it before running anything, and translate it for Gemini.
"""

from typing import Any

TYPES = ("string", "number", "integer", "boolean", "array", "object")
ALLOWED = {"type", "description", "enum", "properties", "required", "items", "minimum", "maximum"}
MAX_PROPERTIES = 20
MAX_DEPTH = 3
MAX_ENUM = 30


class SchemaError(ValueError):
    pass


def validate_definition(schema: Any) -> None:
    """Raise SchemaError, with a message a person can act on, unless ``schema`` is a supported tool schema."""
    if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise SchemaError('The input schema must be a JSON object with "type": "object" and a "properties" object.')
    _node(schema, "input schema", 1)


def _node(node: dict, where: str, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise SchemaError(f"{where}: nesting is deeper than {MAX_DEPTH} levels.")
    extra = set(node) - ALLOWED
    if extra:
        raise SchemaError(f'{where}: "{sorted(extra)[0]}" is not supported. Use only {", ".join(sorted(ALLOWED))}.')
    kind = node.get("type")
    if kind not in TYPES:
        raise SchemaError(f"{where}: type must be one of {', '.join(TYPES)}.")
    if "description" in node and (not isinstance(node["description"], str) or len(node["description"]) > 500):
        raise SchemaError(f"{where}: description must be text of at most 500 characters.")
    if "enum" in node:
        values = node["enum"]
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= MAX_ENUM
            or len(set(map(repr, values))) != len(values)
        ):
            raise SchemaError(f"{where}: enum needs 1 to {MAX_ENUM} different values.")
        if kind == "object" or kind == "array":
            raise SchemaError(f"{where}: enum is only for text and numbers.")
    for bound in ("minimum", "maximum"):
        if bound in node and (isinstance(node[bound], bool) or not isinstance(node[bound], (int, float))):
            raise SchemaError(f"{where}: {bound} must be a number.")
    if kind == "object":
        props = node.get("properties", {})
        if not isinstance(props, dict) or len(props) > MAX_PROPERTIES:
            raise SchemaError(f"{where}: properties must be an object with at most {MAX_PROPERTIES} entries.")
        for name, child in props.items():
            if not isinstance(child, dict):
                raise SchemaError(f"{where}.{name}: must be an object.")
            _node(child, f"{where}.{name}", depth + 1)
        required = node.get("required", [])
        if not isinstance(required, list) or any(r not in props for r in required):
            raise SchemaError(f"{where}: every required name must be one of the properties.")
    elif "properties" in node or "required" in node:
        raise SchemaError(f"{where}: properties and required only belong on objects.")
    if kind == "array":
        if not isinstance(node.get("items"), dict):
            raise SchemaError(f"{where}: arrays need an items schema.")
        _node(node["items"], f"{where}[]", depth + 1)
    elif "items" in node:
        raise SchemaError(f"{where}: items only belongs on arrays.")


def to_gemini(node: dict) -> dict:
    """The same schema in the form Gemini's function declarations expect (upper-case type names)."""
    out: dict[str, Any] = {"type": node["type"].upper()}
    for key in ("description", "enum", "minimum", "maximum"):
        if key in node:
            out[key] = [str(v) for v in node[key]] if key == "enum" else node[key]
    if "properties" in node:
        out["properties"] = {name: to_gemini(child) for name, child in node["properties"].items()}
    if node.get("required"):
        out["required"] = list(node["required"])
    if "items" in node:
        out["items"] = to_gemini(node["items"])
    return out


def check_args(schema: dict, args: Any) -> tuple[dict, dict[str, str]]:
    """Return (arguments with unknown names dropped, error message by argument path)."""
    errors: dict[str, str] = {}
    cleaned = _check(schema, args, "", errors)
    return (cleaned if isinstance(cleaned, dict) else {}), errors


def _check(node: dict, value: Any, path: str, errors: dict[str, str]) -> Any:
    label = path or "arguments"
    kind = node["type"]
    if kind == "object":
        if not isinstance(value, dict):
            errors[label] = "must be an object"
            return {}
        props = node.get("properties", {})
        cleaned = {}
        for name in node.get("required", []):
            if name not in value or value[name] in (None, ""):
                errors[f"{path}.{name}".lstrip(".")] = "is required"
        for name, child in props.items():
            if name in value and value[name] is not None:
                cleaned[name] = _check(child, value[name], f"{path}.{name}".lstrip("."), errors)
        return cleaned
    if kind == "array":
        if not isinstance(value, list):
            errors[label] = "must be a list"
            return []
        return [_check(node["items"], item, f"{path}[{i}]", errors) for i, item in enumerate(value)]
    ok = {
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }[kind]
    if not ok:
        errors[label] = f"must be {'an' if kind in ('integer',) else 'a'} {kind}"
        return value
    if "enum" in node and value not in node["enum"]:
        errors[label] = "must be one of: " + ", ".join(str(v) for v in node["enum"])
    if kind in ("number", "integer"):
        if "minimum" in node and value < node["minimum"]:
            errors[label] = f"must be at least {node['minimum']}"
        if "maximum" in node and value > node["maximum"]:
            errors[label] = f"must be at most {node['maximum']}"
    return value
