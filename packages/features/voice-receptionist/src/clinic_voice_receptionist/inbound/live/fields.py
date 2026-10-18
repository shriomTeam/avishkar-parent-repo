"""Validate and normalise values the model captured, so the database holds clean data."""

import re
from datetime import date
from typing import Any

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_TEXT = 2000


class InvalidValue(ValueError):
    pass


def coerce(field: dict, value: Any) -> Any:
    kind = field["data_type"]
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("true", "yes"):
            return True
        if str(value).strip().lower() in ("false", "no"):
            return False
        raise InvalidValue("must be true or false")
    if kind == "number":
        if isinstance(value, bool):
            raise InvalidValue("must be a number")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise InvalidValue("must be a number") from None
        return int(number) if number.is_integer() else number
    text = str(value).strip()
    if not text:
        raise InvalidValue("must not be empty")
    if kind == "phone":
        compact = re.sub(r"[\s().-]", "", text)
        if not E164.match(compact):
            raise InvalidValue("must be a phone number in E.164 format, for example +14155550123")
        return compact
    if kind == "email":
        if not EMAIL.match(text):
            raise InvalidValue("must be an email address")
        return text.lower()
    if kind == "date":
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise InvalidValue("must be a date as YYYY-MM-DD") from None
    if kind == "enum":
        by_lower = {v.lower(): v for v in field["enum_values"]}
        if text.lower() not in by_lower:
            raise InvalidValue("must be one of: " + ", ".join(field["enum_values"]))
        return by_lower[text.lower()]
    return text[:MAX_TEXT]


def coerce_all(fields: list[dict], args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (valid values by key, error message by key). Unknown keys are reported, never stored."""
    by_key = {f["key"]: f for f in fields}
    valid: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, value in args.items():
        field = by_key.get(key)
        if field is None:
            errors[key] = "not a field of this agent"
            continue
        try:
            valid[key] = coerce(field, value)
        except InvalidValue as exc:
            errors[key] = str(exc)
    return valid, errors
