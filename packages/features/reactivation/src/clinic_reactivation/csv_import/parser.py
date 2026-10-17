"""Bytes in, typed lines out. Strict, whole-file: any error rejects the file.

Pure and in memory: the file is decoded and read from a StringIO, nothing touches disk or a log. Error
messages are fixed sentences with a row number and a column name; a cell value never appears in one.
Row numbers are file line numbers (the header is row 1).
"""

from __future__ import annotations

import csv
import io
import re
from collections import namedtuple
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from clinic_reactivation.csv_import.columns import (
    BY_NAME,
    COLUMN_NAMES,
    COLUMNS,
    DATE,
    FLAG,
    FLAG_FALSE,
    FLAG_TRUE,
    MONEY,
    PATIENT,
    TEXT,
    Column,
)

# Limits. A 10,000-patient, three-year export is roughly 50,000 to 100,000 lines and 10 to 17 MB;
# analyse() takes about 0.3 ms per patient. Tests lower these through the module attributes.
MAX_BYTES = 25 * 1024 * 1024
MAX_ROWS = 150_000
MAX_PATIENTS = 25_000
MAX_ERRORS_SHOWN = 20
MIN_DATE = date(2000, 1, 1)
MAX_AMOUNT_CENTS = 100_000_000  # $1,000,000.00

Line = namedtuple("Line", ["row", *COLUMN_NAMES])  # noqa: PYI024 - built from the column list on purpose

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONEY_RE = re.compile(r"^(-?)(\d{1,9})(?:\.(\d{1,2}))?$")


@dataclass(frozen=True, slots=True)
class CellError:
    row: int
    column: str
    reason: str


class CsvRejected(Exception):
    """The file can't be analysed. `code` is the API error code; `errors` are at most the first 20."""

    def __init__(self, code: str, message: str, *, status: int = 422, errors=(), total: int = 0) -> None:
        super().__init__(code)
        self.code, self.message, self.status = code, message, status
        self.errors, self.total = tuple(errors), total


@dataclass(frozen=True, slots=True)
class ParsedFile:
    lines: list[Line]
    columns: frozenset[str]  # the columns present in the header
    patients: int


class _Bad(ValueError):
    """A cell that can't be read; the message is the fixed reason."""


# --- cell readers: each takes the stripped, non-empty text and returns the typed value ------------------


def _text(col: Column) -> Callable[[str, date], str]:
    def read(raw: str, today: date) -> str:
        if len(raw) > col.max_length:
            raise _Bad(f"is too long (the limit is {col.max_length} characters)")
        return raw

    return read


def _date_reader(col: Column) -> Callable[[str, date], date]:
    def read(raw: str, today: date) -> date:
        if not _DATE_RE.match(raw):
            raise _Bad("must be a date written as YYYY-MM-DD")
        try:
            value = date.fromisoformat(raw)
        except ValueError:
            raise _Bad("is not a real calendar date") from None
        if value < MIN_DATE:
            raise _Bad("is before 2000-01-01")
        if col.name == "visit_date" and value > today:
            raise _Bad("is in the future")
        return value

    return read


def _money_reader(col: Column) -> Callable[[str, date], int]:
    def read(raw: str, today: date) -> int:
        m = _MONEY_RE.match(raw)
        if not m:
            raise _Bad("must be an amount like 12.50, with no currency symbol or thousands separator")
        sign, whole, frac = m.groups()
        if sign and not col.negative_ok:
            raise _Bad("can't be negative")
        cents = int(whole) * 100 + int((frac or "").ljust(2, "0"))
        if cents > MAX_AMOUNT_CENTS:
            raise _Bad("is larger than 1,000,000.00")
        return -cents if sign else cents

    return read


def _choice_reader(col: Column) -> Callable[[str, date], str]:
    allowed = col.values

    def read(raw: str, today: date) -> str:
        value = raw.lower()
        if value not in allowed:
            raise _Bad("must be one of: " + ", ".join(allowed))
        return value

    return read


def _flag_reader(col: Column) -> Callable[[str, date], bool]:
    def read(raw: str, today: date) -> bool:
        value = raw.lower()
        if value in FLAG_TRUE:
            return True
        if value in FLAG_FALSE:
            return False
        raise _Bad("must be yes or no (true, false, 1 and 0 also work)")

    return read


def _reader(col: Column) -> Callable[[str, date], object]:
    return {
        TEXT: _text, DATE: _date_reader, MONEY: _money_reader, FLAG: _flag_reader,
    }.get(col.kind, _choice_reader)(col)  # fmt: skip


_READERS = {c.name: _reader(c) for c in COLUMNS}


# --- errors ----------------------------------------------------------------------------------------------


class _Errors:
    def __init__(self) -> None:
        self.total = 0
        self.shown: list[CellError] = []

    def add(self, row: int, column: str, reason: str) -> None:
        self.total += 1
        if len(self.shown) < MAX_ERRORS_SHOWN:
            self.shown.append(CellError(row, column, reason))

    def raise_if_any(self) -> None:
        if self.total:
            n = self.total
            raise CsvRejected(
                "csv_invalid",
                f"The file has {n} {'problem' if n == 1 else 'problems'}, so nothing was analysed. "
                "Fix them and try again.",
                errors=self.shown,
                total=n,
            )


# --- the parse -------------------------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise CsvRejected("csv_too_large", f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.", status=413)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvRejected(
            "csv_bad_encoding", "The file isn't UTF-8 text. Save it as CSV (UTF-8) and try again."
        ) from None
    if "\x00" in text:
        raise CsvRejected("csv_bad_encoding", "The file isn't a text CSV file.")
    return text


def _header(record: list[str]) -> list[str]:
    names = [cell.strip().lower() for cell in record]
    problems: list[str] = []
    unknown = [n for n in names if n not in BY_NAME]
    if unknown:
        shown = ", ".join(f'"{n[:40]}"' if n else "(blank)" for n in unknown[:10])
        more = f" and {len(unknown) - 10} more" if len(unknown) > 10 else ""
        problems.append(f"Unknown columns: {shown}{more}.")
    seen: set[str] = set()
    dup = sorted({n for n in names if n in BY_NAME and (n in seen or seen.add(n))})
    if dup:
        problems.append("Repeated columns: " + ", ".join(dup) + ".")
    missing = [c.name for c in COLUMNS if c.required and c.name not in names]
    if missing:
        problems.append("Missing required columns: " + ", ".join(missing) + ".")
    if problems:
        raise CsvRejected(
            "csv_invalid_header",
            "The first row doesn't match the template. " + " ".join(problems),
            errors=[CellError(1, "(header)", p) for p in problems],
            total=len(problems),
        )
    return names


def parse_csv(data: bytes, *, today: date) -> ParsedFile:
    """Parse and validate a whole file. Raises CsvRejected; never returns a partial result."""
    text = _decode(data)
    if not text.strip():
        raise CsvRejected("csv_empty", "The file is empty.")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    names: list[str] | None = None
    errors = _Errors()
    lines: list[Line] = []
    start_row = 1
    plan: list[tuple[int, str, Callable, bool]] = []  # (cell index, column, reader, required)
    index_of: dict[str, int] = {}
    data_rows = 0
    try:
        for record in reader:
            row = start_row
            start_row = reader.line_num + 1
            if not any(cell.strip() for cell in record):
                continue
            if names is None:
                names = _header(record)
                index_of = {n: i for i, n in enumerate(names)}
                plan = [(i, n, _READERS[n], BY_NAME[n].required) for n, i in index_of.items()]
                continue
            data_rows += 1
            if data_rows > MAX_ROWS:
                raise CsvRejected("csv_too_many_rows", f"The file has more than {MAX_ROWS:,} rows.", status=413)
            if len(record) != len(names):
                errors.add(row, "(row)", f"has {len(record)} cells but the header has {len(names)}")
                continue
            values: dict[str, object] = {}
            for i, col, read, required in plan:
                raw = record[i].strip()
                if not raw:
                    if required:
                        errors.add(row, col, "is required but empty")
                    continue
                try:
                    values[col] = read(raw, today)
                except _Bad as e:
                    errors.add(row, col, str(e))
            if values.get("line_kind") == "service" and "service_name" in index_of and "service_name" not in values:
                errors.add(row, "service_name", "is required on service lines")
            lines.append(Line(row, *(values.get(n) for n in COLUMN_NAMES)))
    except csv.Error:
        errors.add(max(reader.line_num, 1), "(row)", "isn't valid CSV (check for a stray quote mark)")
        errors.raise_if_any()
    if names is None:
        raise CsvRejected("csv_empty", "The file is empty.")
    if data_rows == 0:
        raise CsvRejected("csv_header_only", "The file has column names but no data rows.")
    columns = frozenset(names)
    if "service_name" not in columns and any(ln.line_kind == "service" for ln in lines):
        errors.add(1, "service_name", "is required because the file has service lines")
    _check_consistency(lines, errors)
    errors.raise_if_any()
    patients = len({ln.patient_id for ln in lines})
    if patients > MAX_PATIENTS:
        raise CsvRejected("csv_too_many_patients", f"The file has more than {MAX_PATIENTS:,} patients.", status=413)
    if not any(is_visit_line(ln) for ln in lines):
        raise CsvRejected(
            "csv_no_visits",
            "The file has no usable visits. A visit needs a service or product line with an amount of 0 or more.",
        )
    return ParsedFile(lines, columns, patients)


def is_visit_line(ln: Line) -> bool:
    """Only a service or product line with an amount of 0 or more makes a visit."""
    return ln.line_kind in ("service", "product") and ln.amount >= 0


# --- agreement between rows --------------------------------------------------------------------------------


def _norm_text(v: object) -> object:
    return " ".join(str(v).split()).casefold()


def _norm_phone(v: object) -> object:
    return re.sub(r"\D", "", str(v))


_NORMALISE: dict[str, Callable[[object], object]] = {
    "patient_name": _norm_text,
    "email": lambda v: str(v).casefold(),
    "phone": _norm_phone,
}


def service_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def _check_consistency(lines: list[Line], errors: _Errors) -> None:
    patient_cols = [c.name for c in COLUMNS if c.level == PATIENT and c.name != "patient_id"]
    first_patient: dict[tuple[str, str], tuple[int, object]] = {}
    visit_owner: dict[str, tuple[int, str, date]] = {}
    visit_type: dict[tuple[str, date, str | None], tuple[int, str]] = {}
    service_cat: dict[str, tuple[int, str]] = {}
    for ln in lines:
        pid = ln.patient_id
        for col in patient_cols:
            v = getattr(ln, col)
            if v is None:
                continue
            norm = _NORMALISE.get(col, lambda x: x)(v)
            seen = first_patient.setdefault((pid, col), (ln.row, norm))
            if seen[1] != norm:
                errors.add(ln.row, col, f"differs from row {seen[0]} for the same patient")
        if ln.visit_id is not None:
            owner = visit_owner.setdefault(ln.visit_id, (ln.row, pid, ln.visit_date))
            if owner[1:] != (pid, ln.visit_date):
                errors.add(ln.row, "visit_id", f"is used for a different patient or date on row {owner[0]}")
        if ln.visit_type is not None:
            key = (pid, ln.visit_date, ln.visit_id)
            seen_type = visit_type.setdefault(key, (ln.row, ln.visit_type))
            if seen_type[1] != ln.visit_type:
                errors.add(ln.row, "visit_type", f"differs from row {seen_type[0]} for the same visit")
        if ln.service_name is not None and ln.service_category is not None:
            key2 = service_key(ln.service_name)
            seen_cat = service_cat.setdefault(key2, (ln.row, service_key(ln.service_category)))
            if seen_cat[1] != service_key(ln.service_category):
                errors.add(ln.row, "service_category", f"differs from row {seen_cat[0]} for the same service")


__all__ = ["CellError", "CsvRejected", "Line", "ParsedFile", "is_visit_line", "parse_csv", "service_key"]
