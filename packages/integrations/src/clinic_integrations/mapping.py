"""Per-client mapping from source columns to canonical fields.

A mapping is data (stored in ``staging.source_mappings``), not code, so onboarding
a client with a new EMR export means writing a mapping, not a migration.
"""

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel


class FieldSpec(BaseModel):
    column: str | None = None
    transform: str | None = None  # "name" or "name:arg", e.g. "date:%d/%m/%Y"
    value: Any = None  # constant, used when column is None
    value_map: dict[str, str] | None = None  # e.g. {"Checked Out": "completed"}


class MappingConfig(BaseModel):
    fields: dict[str, str | FieldSpec]
    unmapped: Literal["attributes", "drop"] = "attributes"
    timezone: str | None = None  # for naive datetimes; defaults to the tenant's

    def spec(self, name: str) -> FieldSpec:
        raw = self.fields[name]
        return FieldSpec(column=raw) if isinstance(raw, str) else raw

    def source_columns(self) -> set[str]:
        return {c for name in self.fields if (c := self.spec(name).column)}


class MappingError(ValueError):
    pass


# --- transforms -----------------------------------------------------------------

_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y"]
_DATETIME_FORMATS = [
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%y %H:%M",
    "%m/%d/%y %I:%M %p",
]


def _date(v: Any, arg: str | None, tz: ZoneInfo) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    for fmt in [arg] if arg else _DATE_FORMATS:
        try:
            return datetime.strptime(str(v).strip(), fmt).date()
        except ValueError:
            continue
    raise MappingError(f"unrecognised date {v!r}")


def _datetime(v: Any, arg: str | None, tz: ZoneInfo) -> datetime:
    if isinstance(v, datetime):
        dt = v
    else:
        s = str(v).strip()
        dt = None
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            for fmt in [arg] if arg else _DATETIME_FORMATS + _DATE_FORMATS:
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise MappingError(f"unrecognised datetime {v!r}")
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def _phone_e164(v: Any, arg: str | None, tz: ZoneInfo) -> str:
    s = str(v).strip()
    digits = re.sub(r"\D", "", s)
    if s.startswith("+") and 8 <= len(digits) <= 15:
        return "+" + digits
    country = arg or "1"
    if len(digits) == 10:
        return f"+{country}{digits}"
    if len(digits) == 11 and digits.startswith(country):
        return "+" + digits
    raise MappingError(f"unrecognised phone {v!r}")


def _money_cents(v: Any, arg: str | None, tz: ZoneInfo) -> int:
    s = str(v).strip().replace(",", "").replace("$", "")
    negative = s.startswith("(") and s.endswith(")")
    try:
        amount = Decimal(s.strip("()"))
    except InvalidOperation:
        raise MappingError(f"unrecognised amount {v!r}") from None
    cents = int((amount * 100).quantize(Decimal("1")))
    return -cents if negative else cents


def _bool(v: Any, arg: str | None, tz: ZoneInfo) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y", "t", "x", "opted in", "subscribed"}


def _name_part(index: int) -> Callable[[Any, str | None, ZoneInfo], str]:
    def split(v: Any, arg: str | None, tz: ZoneInfo) -> str:
        s = str(v).strip()
        if "," in s:  # "Last, First"
            last, _, first = s.partition(",")
            parts = [first.strip(), last.strip()]
        else:
            first, _, last = s.partition(" ")
            parts = [first.strip(), last.strip()]
        return parts[index]

    return split


TRANSFORMS: dict[str, Callable[[Any, str | None, ZoneInfo], Any]] = {
    "strip": lambda v, a, tz: str(v).strip(),
    "lower": lambda v, a, tz: str(v).strip().lower(),
    "upper": lambda v, a, tz: str(v).strip().upper(),
    "title": lambda v, a, tz: str(v).strip().title(),
    "int": lambda v, a, tz: int(float(str(v).replace(",", ""))),
    "bool": _bool,
    "date": _date,
    "datetime": _datetime,
    "phone_e164": _phone_e164,
    "money_cents": _money_cents,
    "first_name": _name_part(0),
    "last_name": _name_part(1),
}


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() in {"", "NULL", "null", "N/A", "n/a"})


def apply_mapping(row: dict[str, Any], config: MappingConfig, tz: ZoneInfo) -> tuple[dict[str, Any], dict]:
    """Return (canonical fields, leftover attributes). Raises MappingError on bad values."""
    out: dict[str, Any] = {}
    for name in config.fields:
        spec = config.spec(name)
        raw = row.get(spec.column) if spec.column else spec.value
        if _is_blank(raw):
            out[name] = None
            continue
        if spec.value_map is not None:
            raw = spec.value_map.get(str(raw).strip(), raw)
        if spec.transform:
            tname, _, arg = spec.transform.partition(":")
            try:
                fn = TRANSFORMS[tname]
            except KeyError:
                raise MappingError(f"unknown transform {tname!r} on field {name!r}") from None
            try:
                raw = fn(raw, arg or None, tz)
            except MappingError as e:
                raise MappingError(f"{name}: {e}") from None
        out[name] = raw

    attributes: dict = {}
    if config.unmapped == "attributes":
        used = config.source_columns()
        attributes = {
            k: (v.isoformat() if isinstance(v, date | datetime) else v)
            for k, v in row.items()
            if k not in used and not _is_blank(v)
        }
    return out, attributes
