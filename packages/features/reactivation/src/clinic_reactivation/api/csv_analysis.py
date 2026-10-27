"""Import CSV: analyse a file live and return the result. The file is never stored.

Nothing from the file reaches the database, a queue, the disk or a log. The body is read from the request
stream into memory (not multipart, whose upload objects spill to a temp file above 1 MB), parsed, turned
into the same ``PatientFacts`` the database loader builds, and run through the same ``analyse()``. The only
write is one audit row holding counts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session
from clinic_core.audit import audit
from clinic_db.models.core import Patient, Tenant
from clinic_db.models.reactivation import Run, Settings
from clinic_reactivation.analysis.engine import RunFailed, RunResult, analyse
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.api.results import TypeOut, offer_service_id, patient_value_range, type_entries
from clinic_reactivation.api.roles import MANAGERS, VIEWERS
from clinic_reactivation.csv_import import columns as cols
from clinic_reactivation.csv_import import parser
from clinic_reactivation.csv_import.build import Built, build_facts
from clinic_reactivation.csv_import.parser import CsvRejected

log = logging.getLogger(__name__)
router = APIRouter()

TIMEOUT_SECONDS = 60
MAX_CONCURRENT = 2  # analyses at once per API process; each holds up to ~25 MB of the file plus its facts
_slots = asyncio.Semaphore(MAX_CONCURRENT)
_BOTH_FLAGS = {"do_not_contact", "deceased"}


# --- shapes ----------------------------------------------------------------------------------------------


class CsvPatientOut(BaseModel):
    patient_id: str  # derived from the file's own id; meaningful only inside this analysis
    external_id: str  # the id as written in the file
    display_name: str | None
    status: str
    primary_type: str | None
    matched_types: list[str]
    reasons: list[str]
    usual_service_name: str | None
    last_visit_day: str | None
    days_since_last_visit: int
    likelihood_score: int
    revenue_basis_cents: int
    overdue_ratio: float
    revenue_kind: str | None
    revenue_low_cents: int | None
    revenue_high_cents: int | None
    offer_service_name: str | None
    points: dict[str, Any]


class CsvCounts(BaseModel):
    rows: int
    patients: int
    visit_days: int


class CsvNote(BaseModel):
    code: str
    patients: int


class CsvAnalysis(BaseModel):
    source: str
    settings_source: str
    settings_version: int
    settings: ReactivationSettings
    rate_basis: str
    as_of: datetime
    counts: CsvCounts
    notes: list[CsvNote]
    summary: dict[str, Any]
    quality: dict[str, Any]
    types: list[TypeOut]
    patients: list[CsvPatientOut]


class ColumnOut(BaseModel):
    name: str
    kind: str
    required: bool
    description: str
    if_missing: str
    example: str
    values: list[str]
    max_length: int


class CsvLimits(BaseModel):
    max_bytes: int
    max_rows: int
    max_patients: int


class ColumnsOut(BaseModel):
    columns: list[ColumnOut]
    notes: list[str]
    limits: CsvLimits


class DataStatus(BaseModel):
    has_patients: bool
    has_completed_run: bool


# --- errors ----------------------------------------------------------------------------------------------


def _reject(e: CsvRejected) -> HTTPException:
    detail = {
        "code": e.code,
        "message": e.message,
        "total_errors": e.total,
        "errors": [{"row": x.row, "column": x.column, "reason": x.reason} for x in e.errors],
    }
    return HTTPException(e.status, detail)


def _fail(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, {"code": code, "message": message, "total_errors": 0, "errors": []})


async def _read_body(request: Request) -> bytes:
    limit = parser.MAX_BYTES
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise _reject(CsvRejected("csv_too_large", f"The file is larger than {limit // (1024 * 1024)} MB.", status=413))
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise _reject(
                CsvRejected("csv_too_large", f"The file is larger than {limit // (1024 * 1024)} MB.", status=413)
            )
    return bytes(body)


# --- the analysis -----------------------------------------------------------------------------------------


def _present(result: RunResult, built: Built, columns: frozenset[str]) -> dict[str, Any]:
    """The results API's shapes for a file result. Everything the file cannot supply is said so here."""
    data = result.to_dict()
    names = built.service_names
    facts = {f.patient_id: f for f in built.facts}
    rates = {t.type_key: t for t in result.types}
    by_str_id = {str(k): v for k, v in names.items()}
    patients: list[CsvPatientOut] = []
    for row, j in zip(result.patients, data["patients"], strict=True):
        points = j["points"]
        if "best_time" in points:  # the engine's "fewer than 3 visits" would be wrong: files carry no times
            points["best_time"] = {"weekday": None, "band": None, "reason": "needs_visit_times"}
        last = facts[row.patient_id].last_visit_day
        external = built.external_ids[row.patient_id]
        rate = rates.get(row.primary_type) if row.status == "dormant" and row.primary_type else None
        low, high = (None, None)
        if rate is not None:
            low, high = patient_value_range(row.revenue_basis_cents, rate.revenue_kind, rate.rate_low, rate.rate_high)
        patients.append(
            CsvPatientOut(
                patient_id=str(row.patient_id),
                external_id=external,
                display_name=built.display_names[row.patient_id],
                status=row.status,
                primary_type=row.primary_type,
                matched_types=list(row.matched_types),
                reasons=list(row.reasons),
                usual_service_name=names.get(row.usual_service_id) if row.usual_service_id else None,
                last_visit_day=last.isoformat() if last else None,
                days_since_last_visit=row.days_since_last_visit,
                likelihood_score=row.likelihood_score,
                revenue_basis_cents=row.revenue_basis_cents,
                overdue_ratio=float(row.overdue_ratio),
                revenue_kind=rate.revenue_kind if low is not None and rate is not None else None,
                revenue_low_cents=low,
                revenue_high_cents=high,
                offer_service_name=by_str_id.get(offer_service_id(points) or ""),
                points=points,
            )
        )
    quality = data["quality"]
    if _BOTH_FLAGS <= columns:  # the warning stays unless the file supplied both exclusion flags
        quality["exclusion_flags_not_importable"] = False
    return {"summary": data["summary"], "quality": quality, "patients": patients}


def analyse_file(
    data: bytes,
    *,
    settings: ReactivationSettings,
    tz_name: str,
    requires_opt_in: bool,
    now: datetime,
) -> tuple[RunResult, Built, parser.ParsedFile]:
    """Parse, build and analyse. Pure and synchronous, so the endpoint can run it in a thread."""
    today = now.astimezone(ZoneInfo(tz_name)).date()
    parsed = parser.parse_csv(data, today=today)
    built = build_facts(
        parsed, today=today, requires_opt_in=requires_opt_in, cohort_min=settings.limits.spend_cohort_minimum
    )
    result = analyse(
        built.facts, settings, {}, {}, None, now, tz_name, service_names=built.service_names, verify_determinism=True
    )
    return result, built, parsed


async def _run_in_slot(data: bytes, **kwargs: Any) -> tuple[RunResult, Built, parser.ParsedFile]:
    """Analyse in a worker thread under the time limit. The caller already holds a slot and hands it to the
    thread. A thread can't be stopped, so after a timeout the slot stays taken until the thread really
    finishes; timeouts therefore can't pile up threads."""
    work = asyncio.ensure_future(asyncio.to_thread(analyse_file, data, **kwargs))
    work.add_done_callback(lambda _: _slots.release())
    return await asyncio.wait_for(asyncio.shield(work), TIMEOUT_SECONDS)


@router.post("/csv-analysis", response_model=CsvAnalysis, dependencies=MANAGERS)
async def csv_analysis(
    request: Request,
    session: AsyncSession = Depends(get_session),
    ctx: RequestContext = Depends(get_request_context),
) -> CsvAnalysis:
    """Body: the CSV file as raw bytes with ``Content-Type: text/csv``."""
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "text/csv":
        raise _fail(415, "csv_wrong_type", "Send the file as text/csv.")
    if _slots.locked():
        raise _fail(429, "csv_busy", "Another file is being analysed. Try again in a moment.")
    # Taken before the body is read, so at most MAX_CONCURRENT files are ever held in memory. The slot is free,
    # so this does not wait, and no other request can run between the check and the acquire.
    await _slots.acquire()
    began = time.monotonic()
    try:
        data = await _read_body(request)
        tenant = await session.get(Tenant, ctx.tenant_id)
        try:
            ZoneInfo(tenant.timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise _fail(422, "bad_timezone", "The practice's time zone is not recognised.") from None
        saved = await session.scalar(select(Settings))
        try:
            settings = ReactivationSettings.model_validate(saved.config if saved else {})
        except ValueError:
            raise _fail(422, "bad_settings", "The saved settings no longer pass validation.") from None
    except BaseException:
        _slots.release()  # the analysis never started, so no thread will release it
        raise
    now = datetime.now(UTC)
    try:
        result, built, parsed = await _run_in_slot(
            data,
            settings=settings,
            tz_name=tenant.timezone,
            requires_opt_in=bool((tenant.settings or {}).get("sms_requires_explicit_opt_in", True)),
            now=now,
        )
    except CsvRejected as e:
        log.info("csv analysis rejected: %s (%d problems)", e.code, e.total)
        raise _reject(e) from None
    except TimeoutError:
        log.warning("csv analysis timed out after %ds (%d bytes)", TIMEOUT_SECONDS, len(data))
        raise _fail(504, "csv_timed_out", "The file took too long to analyse. Try a smaller file.") from None
    except RunFailed as e:
        raise _fail(422, e.error_code, "The analysis couldn't finish. Check the file and your settings.") from None
    except Exception as e:  # noqa: BLE001 - class name only: the message could carry patient data
        log.error("csv analysis failed: %s", type(e).__name__)
        raise _fail(500, "internal_error", "Something went wrong analysing the file.") from None

    body = _present(result, built, parsed.columns)
    names = built.service_names
    types = type_entries(
        settings.model_dump(mode="json"),
        body["summary"],
        {t.type_key: (t, names.get(t.top_service_id)) for t in result.types},
    )
    elapsed = time.monotonic() - began
    await audit(
        session,
        "reactivation.csv_analysis.run",
        actor_type="staff",
        actor_id=ctx.actor_id,
        details={
            "rows": len(parsed.lines),
            "patients": parsed.patients,
            "visit_days": built.visit_days,
            "dormant_count": body["summary"]["dormant_count"],
            "bytes": len(data),
            "duration_ms": round(elapsed * 1000),
        },
    )
    log.info("csv analysis: %d rows, %d patients, %.1fs", len(parsed.lines), parsed.patients, elapsed)
    return CsvAnalysis(
        source="csv",
        settings_source="saved" if saved else "defaults",
        settings_version=saved.version if saved else 0,
        settings=settings,
        rate_basis="assumed",
        as_of=now,
        counts=CsvCounts(rows=len(parsed.lines), patients=parsed.patients, visit_days=built.visit_days),
        notes=[CsvNote(code=k, patients=v) for k, v in sorted(built.notes.items())],
        types=types,
        **body,
    )


# --- the column definition, the template, and whether there is saved data -----------------------------------


@router.get("/csv-columns", response_model=ColumnsOut, dependencies=MANAGERS)
async def csv_columns() -> ColumnsOut:
    return ColumnsOut(
        columns=[
            ColumnOut(
                name=c.name, kind=c.kind, required=c.required, description=c.description,
                if_missing=c.if_missing, example=c.example, values=list(c.values), max_length=c.max_length,
            )
            for c in cols.COLUMNS
        ],
        notes=list(cols.NOTES),
        limits=CsvLimits(max_bytes=parser.MAX_BYTES, max_rows=parser.MAX_ROWS, max_patients=parser.MAX_PATIENTS),
    )  # fmt: skip


@router.get("/csv-template", dependencies=MANAGERS)
async def csv_template() -> Response:
    return Response(
        cols.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="dormant-patients-template.csv"'},
    )


@router.get("/data-status", response_model=DataStatus, dependencies=VIEWERS)
async def data_status(session: AsyncSession = Depends(get_session)) -> DataStatus:
    """No data means no patients and no completed run; the Overview shows the welcome page then."""
    has_patients = await session.scalar(select(select(Patient.id).limit(1).exists()))
    has_run = await session.scalar(select(select(Run.id).where(Run.status == "completed").limit(1).exists()))
    return DataStatus(has_patients=bool(has_patients), has_completed_run=bool(has_run))
