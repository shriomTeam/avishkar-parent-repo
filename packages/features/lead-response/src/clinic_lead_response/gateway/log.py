"""Logging that cannot carry personal data. Only a fixed set of field names is accepted, and a phone number is masked to
its last two digits. The message body and credentials have no field, so they cannot be logged by mistake."""

import logging
import re
import uuid

ALLOWED_FIELDS = frozenset(
    {
        "tenant_id",
        "trace_id",
        "message_id",
        "lane",
        "purpose",
        "attempt",
        "outcome",
        "status",
        "reason",
        "provider",
        "provider_error_code",
        "http_status",
        "duration_ms",
        "to_masked",
        "queries",
    }
)

_SAFE = re.compile(r"[^A-Za-z0-9_.:*\-/]")


def mask_phone(number: str | None) -> str:
    digits = re.sub(r"\D", "", number or "")
    return f"***{digits[-2:]}" if len(digits) >= 4 else "***"


def _value(value: object) -> str:
    if isinstance(value, uuid.UUID):
        return str(value)
    text = str(value)
    return _SAFE.sub("_", text)[:64]


def format_fields(**fields: object) -> str:
    unknown = set(fields) - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"not a loggable field: {sorted(unknown)}")  # a programmer error, never data-dependent
    return " ".join(f"{name}={_value(fields[name])}" for name in sorted(fields) if fields[name] is not None)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: object) -> None:
    logger.log(level, "%s %s", event, format_fields(**fields))
