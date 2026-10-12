"""Client data onboarding: upload an export, review the suggested mapping, import.

Mappings are saved per (tenant, source system, entity), so the next export from
the same EMR imports without any setup.
"""

import json
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session
from clinic_core.database import current_tenant
from clinic_db.models.core import Tenant
from clinic_db.models.staging import ImportBatch, RawRecord, SourceMapping
from clinic_integrations import (
    ENTITY_MODELS,
    IMPORT_ORDER,
    ImportBlocked,
    MappingConfig,
    MappingError,
    apply_mapping,
    run_import,
    suggest_mapping,
)
from clinic_integrations.sources import CsvSource, ExcelSource

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


async def _source(file: UploadFile) -> CsvSource | ExcelSource:
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large for direct upload")
    name = (file.filename or "").lower()
    return ExcelSource(content) if name.endswith((".xlsx", ".xlsm")) else CsvSource(content)


def _entity(entity_type: str) -> str:
    if entity_type not in ENTITY_MODELS:
        raise HTTPException(422, f"entity_type must be one of {IMPORT_ORDER}")
    return entity_type


class SuggestOut(BaseModel):
    entity_type: str
    headers: list[str]
    canonical_fields: list[str]
    mapping: MappingConfig
    preview: list[dict]


@router.post("/suggest", response_model=SuggestOut)
async def suggest(
    entity_type: str = Form(...),
    source_system: str = Form("csv"),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> SuggestOut:
    entity_type = _entity(entity_type)
    source = await _source(file)
    rows = []
    for row in source.rows():
        rows.append(row)
        if len(rows) == 5:
            break
    headers = list(rows[0]) if rows else []
    saved = await session.scalar(
        select(SourceMapping.config).where(
            SourceMapping.source_system == source_system, SourceMapping.entity_type == entity_type
        )
    )
    mapping = MappingConfig.model_validate(saved) if saved else suggest_mapping(entity_type, headers)

    tenant = await session.get(Tenant, current_tenant(session))
    preview = []
    for row in rows:
        try:
            values, _ = apply_mapping(row, mapping, ZoneInfo(tenant.timezone))
            ENTITY_MODELS[entity_type].model_validate(values)
            preview.append({"ok": True, "values": json.loads(json.dumps(values, default=str))})
        except (MappingError, ValidationError) as e:
            preview.append({"ok": False, "error": str(e)})
    return SuggestOut(
        entity_type=entity_type,
        headers=headers,
        canonical_fields=list(ENTITY_MODELS[entity_type].model_fields),
        mapping=mapping,
        preview=preview,
    )


class ImportStats(BaseModel):
    total: int
    created: int
    updated: int
    errors: int


class RowError(BaseModel):
    row: int
    error: str


class ImportOut(BaseModel):
    batch_id: uuid.UUID
    entity_type: str
    stats: ImportStats
    errors: list[RowError]


@router.post("", response_model=ImportOut, status_code=201)
async def create_import(
    entity_type: str = Form(...),
    source_system: str = Form("csv", description="e.g. csv, boulevard_export, zenoti_export"),
    mapping: str = Form(..., description="MappingConfig JSON, usually the reviewed /suggest output"),
    save_mapping: bool = Form(True),
    file: UploadFile = File(...),
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> ImportOut:
    entity_type = _entity(entity_type)
    try:
        config = MappingConfig.model_validate_json(mapping)
    except ValidationError as e:
        raise HTTPException(422, f"invalid mapping: {e}") from None
    try:
        result = await run_import(
            session,
            source=await _source(file),
            source_system=source_system,
            entity_type=entity_type,
            mapping=config,
            filename=file.filename,
            actor_id=ctx.actor_id,
        )
    except ImportBlocked as e:
        raise HTTPException(409, str(e)) from None
    if save_mapping:
        stmt = insert(SourceMapping).values(
            tenant_id=ctx.tenant_id,
            source_system=source_system,
            entity_type=entity_type,
            config=config.model_dump(exclude_none=True),
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SourceMapping.tenant_id, SourceMapping.source_system, SourceMapping.entity_type],
                set_={"config": stmt.excluded.config},
            )
        )
    return ImportOut(batch_id=result.batch_id, entity_type=entity_type, stats=result.stats(), errors=result.errors)


class BatchOut(BaseModel):
    id: uuid.UUID
    source_system: str
    entity_type: str
    filename: str | None
    status: str
    stats: dict
    created_at: datetime


@router.get("", response_model=list[BatchOut])
async def list_imports(session: AsyncSession = Depends(get_session)) -> list[ImportBatch]:
    return list((await session.scalars(select(ImportBatch).order_by(ImportBatch.created_at.desc()).limit(100))).all())


@router.get("/{batch_id}/errors")
async def import_errors(batch_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = await session.scalars(
        select(RawRecord)
        .where(RawRecord.batch_id == batch_id, RawRecord.status == "error")
        .order_by(RawRecord.row_number)
        .limit(500)
    )
    return [{"row": r.row_number, "error": r.error, "data": r.data} for r in rows]
