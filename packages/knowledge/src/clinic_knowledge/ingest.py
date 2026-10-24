"""Turning an uploaded file into searchable passages: read, clean, split, embed, save.

Safe to run more than once for the same document (a queue may deliver a job twice): a document that is already
``ready`` or ``duplicate`` is left alone, and passages are replaced as a set.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from clinic_core.database import tenant_session
from clinic_db.models.knowledge import Chunk, Document
from clinic_knowledge.chunking import split
from clinic_knowledge.config import KnowledgeSettings
from clinic_knowledge.constants import DUPLICATE, FAILED, PROCESSING, READY, UPLOADED
from clinic_knowledge.embeddings import Embedder, EmbeddingError
from clinic_knowledge.extract import ExtractError, extract, normalize, text_hash
from clinic_knowledge.storage import FileStore

log = logging.getLogger("knowledge.ingest")

MAX_ATTEMPTS = 3


async def fail(tenant_id: uuid.UUID, document_id: uuid.UUID, message: str, database_url: str | None = None) -> None:
    async with tenant_session(tenant_id, database_url=database_url) as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.status, document.error = FAILED, message[:300]


async def run(
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    *,
    store: FileStore,
    embedder: Embedder,
    settings: KnowledgeSettings,
    database_url: str | None = None,
) -> None:
    async with tenant_session(tenant_id, database_url=database_url) as session:
        document = await session.get(Document, document_id)
        if document is None or document.status not in (UPLOADED, PROCESSING):
            return  # deleted meanwhile, or already finished
        if document.attempts >= MAX_ATTEMPTS:
            document.status, document.error = FAILED, "This file could not be processed. Please try again later."
            return
        document.status, document.attempts = PROCESSING, document.attempts + 1
        object_name, filename, replaces_id = document.object_name, document.filename, document.replaces_id

    try:
        raw = await store.get(object_name)
        if raw is None:
            raise ExtractError("The uploaded file could not be found. Please upload it again.")
        blocks = extract(raw, filename)
        whole = text_hash(normalize("\n\n".join(b.text for b in blocks)))
        passages = split(blocks)
        if not passages:
            raise ExtractError("No readable text was found in this file.")
        # A passage already kept in another document of this clinic is not stored or paid for again.
        async with tenant_session(tenant_id, database_url=database_url) as session:
            known = dict(
                (
                    await session.execute(
                        select(Chunk.text_hash, Chunk.document_id).where(
                            Chunk.document_id != document_id,
                            Chunk.document_id != (replaces_id or uuid.UUID(int=0)),
                        )
                    )
                ).all()
            )
        fresh = [p for p in passages if text_hash(normalize(p.text)) not in known]
        if not fresh:
            same_as = known[text_hash(normalize(passages[0].text))]
            async with tenant_session(tenant_id, database_url=database_url) as session:
                document = await session.get(Document, document_id)
                other = await session.get(Document, same_as)
                if document is not None:
                    document.status, document.duplicate_of_id, document.text_hash = DUPLICATE, same_as, whole
                    document.error = (
                        f"Everything in this file is already in “{other.filename if other else 'another file'}”."
                    )
            return
        passages = fresh
        vectors = await embedder.embed_documents([p.text for p in passages])
    except (ExtractError, EmbeddingError) as exc:
        log.info("document %s failed: %s", document_id, type(exc).__name__)
        await fail(tenant_id, document_id, str(exc), database_url)
        return
    except Exception:
        log.exception("document %s failed unexpectedly", document_id)
        await fail(tenant_id, document_id, "Something went wrong while reading this file.", database_url)
        return

    replaced_object: str | None = None
    async with tenant_session(tenant_id, database_url=database_url) as session:
        document = await session.get(Document, document_id)
        if document is None:
            return  # deleted while we worked
        same_text = await session.scalar(
            select(Document).where(Document.text_hash == whole, Document.id != document_id, Document.status == READY)
        )
        if same_text is not None and document.replaces_id != same_text.id:
            document.status, document.duplicate_of_id, document.text_hash = DUPLICATE, same_text.id, whole
            document.error = f"Same content as “{same_text.filename}”, so it was not added again."
            return
        total = (await session.scalar(select(func.count()).select_from(Chunk))) or 0
        reclaimed = 0
        if document.replaces_id:
            reclaimed = (
                await session.scalar(
                    select(func.count()).select_from(Chunk).where(Chunk.document_id == document.replaces_id)
                )
            ) or 0
        if total - reclaimed + len(passages) > settings.max_chunks:
            document.status = FAILED
            document.error = "This would go over your clinic's knowledge base size limit."
            return
        await session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        session.add_all(
            Chunk(
                tenant_id=tenant_id,
                document_id=document_id,
                ordinal=i,
                heading=p.heading,
                text=p.text,
                text_hash=text_hash(normalize(p.text)),
                token_estimate=p.tokens,
                embedding=vector,
            )
            for i, (p, vector) in enumerate(zip(passages, vectors, strict=True))
        )
        document.status, document.error, document.text_hash = READY, None, whole
        document.chunk_count, document.processed_at = len(passages), datetime.now(UTC)
        if document.replaces_id:
            old = await session.get(Document, document.replaces_id)
            if old is not None:
                replaced_object = old.object_name
                await session.delete(old)
            document.replaces_id = None
    if replaced_object:
        await store.delete(replaced_object)
