"""The clinic's knowledge base: the files agents can look things up in. The work itself is in ``clinic_knowledge``."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_core.api import RequestContext, get_request_context, get_session, require_role
from clinic_core.audit import audit
from clinic_core.database import tenant_session
from clinic_db.models.core import StaffRole
from clinic_knowledge import queue, search, service
from clinic_knowledge.config import get_knowledge_settings
from clinic_knowledge.embeddings import EmbeddingError
from clinic_knowledge.storage import store_for

router = APIRouter(prefix="/inbound/knowledge", tags=["voice_receptionist"])

MANAGERS = [Depends(require_role(StaffRole.OWNER, StaffRole.OFFICE_MANAGER))]


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    filename: str
    size_bytes: int
    status: str  # uploaded, processing, ready, failed, duplicate
    error: str | None
    chunk_count: int
    replaces_id: uuid.UUID | None
    created_at: datetime
    processed_at: datetime | None


class KnowledgeOut(BaseModel):
    documents: list[DocumentOut]
    max_documents: int
    max_file_bytes: int
    enabled: bool  # false when file storage is not set up on this server


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=search.MAX_QUERY_CHARS)


class SearchHitOut(BaseModel):
    document_id: uuid.UUID
    filename: str
    heading: str | None
    text: str
    similarity: float


class SearchOut(BaseModel):
    results: list[SearchHitOut]


def _store(request: Request):
    store = store_for(request.app, get_knowledge_settings())
    if store is None:
        raise HTTPException(409, "File storage is not set up on this server, so documents cannot be added.")
    return store


def _staff_id(ctx: RequestContext) -> uuid.UUID | None:
    try:
        return uuid.UUID(ctx.actor_id)
    except ValueError:
        return None


@router.get("/documents", response_model=KnowledgeOut)
async def list_documents(request: Request, session: AsyncSession = Depends(get_session)) -> KnowledgeOut:
    settings = get_knowledge_settings()
    return KnowledgeOut(
        documents=[DocumentOut.model_validate(d) for d in await service.list_documents(session)],
        max_documents=settings.max_documents,
        max_file_bytes=settings.max_file_bytes,
        enabled=store_for(request.app, settings) is not None,
    )


@router.post("/documents", response_model=DocumentOut, status_code=201, dependencies=MANAGERS)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File()],
    same_name: Annotated[Literal["replace", "keep"] | None, Form()] = None,
    ctx: RequestContext = Depends(get_request_context),
) -> DocumentOut:
    """Save the file, then start reading it in the background. The row is committed before the job starts."""
    settings, store = get_knowledge_settings(), _store(request)
    data = await file.read(settings.max_file_bytes + 1)  # never read more than one byte past the limit
    try:
        async with tenant_session(ctx.tenant_id, database_url=ctx.database_url) as session:
            document = await service.upload(
                session,
                tenant_id=ctx.tenant_id,
                staff_id=_staff_id(ctx),
                filename=file.filename or "",
                data=data,
                store=store,
                settings=settings,
                same_name=same_name,
            )
            await audit(
                session,
                "voice.knowledge.uploaded",
                actor_type="staff",
                actor_id=ctx.actor_id,
                entity_type="knowledge.document",
                entity_id=document.id,
            )
            out = DocumentOut.model_validate(document)
    except service.SameFile as exc:
        raise HTTPException(409, {"code": "same_file", "message": str(exc)}) from None
    except service.SameName as exc:
        raise HTTPException(409, {"code": "same_name", "message": str(exc)}) from None
    except service.KnowledgeError as exc:
        raise HTTPException(422, str(exc)) from None
    await queue.enqueue(request.app, ctx.tenant_id, out.id, store, settings, ctx.database_url)
    return out


@router.post("/documents/{document_id}/retry", response_model=DocumentOut, dependencies=MANAGERS)
async def retry_document(
    document_id: uuid.UUID, request: Request, ctx: RequestContext = Depends(get_request_context)
) -> DocumentOut:
    store = _store(request)
    try:
        async with tenant_session(ctx.tenant_id, database_url=ctx.database_url) as session:
            out = DocumentOut.model_validate(await service.retry(session, document_id))
    except service.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    except service.KnowledgeError as exc:
        raise HTTPException(409, str(exc)) from None
    await queue.enqueue(request.app, ctx.tenant_id, document_id, store, get_knowledge_settings(), ctx.database_url)
    return out


@router.delete("/documents/{document_id}", status_code=204, dependencies=MANAGERS)
async def delete_document(
    document_id: uuid.UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove the file and everything searchable made from it."""
    try:
        await service.delete(session, document_id, _store(request))
    except service.NotFound as exc:
        raise HTTPException(404, str(exc)) from None
    await audit(
        session,
        "voice.knowledge.deleted",
        actor_type="staff",
        actor_id=ctx.actor_id,
        entity_type="knowledge.document",
        entity_id=document_id,
    )


@router.post("/search", response_model=SearchOut)
async def test_search(body: SearchIn, request: Request, session: AsyncSession = Depends(get_session)) -> SearchOut:
    """What an agent would find for this question. For staff to check their documents answer what callers ask."""
    if not body.query.strip():
        raise HTTPException(422, "Type a question to search for.")
    embedder = queue.embedder_for(request.app, get_knowledge_settings())
    try:
        hits = await search.search(session, body.query, embedder=embedder, limit=5)
    except EmbeddingError as exc:
        raise HTTPException(503, str(exc)) from None
    return SearchOut(
        results=[
            SearchHitOut(
                document_id=h.document_id, filename=h.filename, heading=h.heading, text=h.text, similarity=h.similarity
            )
            for h in hits
        ]
    )
