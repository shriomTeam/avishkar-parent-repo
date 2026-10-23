"""Documents in a clinic's knowledge base: upload, list, retry, delete. Everything runs inside a tenant session."""

import hashlib
import os
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clinic_db.models.knowledge import Chunk, Document
from clinic_knowledge.config import KnowledgeSettings
from clinic_knowledge.constants import ALLOWED_TYPES, FAILED, IN_PROGRESS, UPLOADED
from clinic_knowledge.storage import FileStore, object_name


class KnowledgeError(Exception):
    """A problem the user can fix; the message is shown to them as written."""


class SameFile(KnowledgeError):
    """This exact file is already in the knowledge base."""

    def __init__(self, existing: Document):
        super().__init__(f"“{existing.filename}” is already in your knowledge base.")
        self.existing = existing


class SameName(KnowledgeError):
    """A different file with this name exists: the caller must choose to replace it or keep both."""

    def __init__(self, existing: Document):
        super().__init__(f"A different file named “{existing.filename}” is already in your knowledge base.")
        self.existing = existing


class NotFound(KnowledgeError):
    pass


def safe_filename(name: str) -> str:
    """Only the last path part, no control characters, at most 255 characters."""
    base = os.path.basename(name.replace("\\", "/")).strip()
    base = "".join(c for c in base if c.isprintable())
    return base[:255]


async def get_document(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await session.get(Document, document_id)
    if document is None:
        raise NotFound("That document does not exist.")
    return document


async def list_documents(session: AsyncSession) -> list[Document]:
    return list((await session.scalars(select(Document).order_by(Document.created_at.desc()))).all())


async def upload(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    staff_id: uuid.UUID | None,
    filename: str,
    data: bytes,
    store: FileStore,
    settings: KnowledgeSettings,
    same_name: str | None = None,
) -> Document:
    """Store a file and add its row (status ``uploaded``). ``same_name`` is ``"replace"`` or ``"keep"``."""
    filename = safe_filename(filename)
    extension = os.path.splitext(filename)[1].lower()
    if extension not in ALLOWED_TYPES:
        raise KnowledgeError("Only PDF, Word (.docx), text (.txt) and Markdown (.md) files can be added.")
    if not data:
        raise KnowledgeError("That file is empty.")
    if len(data) > settings.max_file_bytes:
        raise KnowledgeError(f"Files can be up to {settings.max_file_bytes // (1024 * 1024)} MB.")

    content_hash = hashlib.sha256(data).hexdigest()
    same_file = await session.scalar(select(Document).where(Document.content_hash == content_hash))
    if same_file is not None:
        raise SameFile(same_file)

    count = await session.scalar(select(func.count()).select_from(Document))
    existing = await session.scalar(
        select(Document).where(func.lower(Document.filename) == filename.lower()).order_by(Document.created_at.desc())
    )
    # Replacing swaps one document for another once the new one is ready, so it does not need a free slot of its own
    # until then; keeping both does.
    if existing is not None and same_name not in ("replace", "keep"):
        raise SameName(existing)
    if (count or 0) >= settings.max_documents and not (existing is not None and same_name == "replace"):
        raise KnowledgeError(f"A clinic can keep up to {settings.max_documents} documents. Delete one to add another.")

    document_id = uuid.uuid4()
    name = object_name(tenant_id, document_id, filename)
    await store.put(name, data, ALLOWED_TYPES[extension])
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        filename=filename,
        content_type=ALLOWED_TYPES[extension],
        size_bytes=len(data),
        content_hash=content_hash,
        status=UPLOADED,
        object_name=name,
        replaces_id=existing.id if existing is not None and same_name == "replace" else None,
        created_by_staff_id=staff_id,
    )
    session.add(document)
    await session.flush()
    return document


async def retry(session: AsyncSession, document_id: uuid.UUID) -> Document:
    document = await get_document(session, document_id)
    if document.status != FAILED:
        raise KnowledgeError("Only a document that failed can be tried again.")
    document.status, document.error, document.attempts = UPLOADED, None, 0
    await session.flush()
    return document


async def delete(session: AsyncSession, document_id: uuid.UUID, store: FileStore) -> None:
    """Remove the row (its passages go with it, by cascade) and then the stored file."""
    document = await get_document(session, document_id)
    name = document.object_name
    await session.delete(document)
    await session.flush()
    await store.delete(name)


async def chunk_total(session: AsyncSession) -> int:
    return (await session.scalar(select(func.count()).select_from(Chunk))) or 0


def is_busy(document: Document) -> bool:
    return document.status in IN_PROGRESS
