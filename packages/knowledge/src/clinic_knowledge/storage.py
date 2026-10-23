"""Where uploaded files are kept: the knowledge-base/ folder of the private files bucket, one folder per clinic.

The service account can reach every clinic's files and row-level security does not cover storage, so object names
are built here from the clinic and document ids only. Nothing from a request ever becomes part of an object name.
"""

import asyncio
import logging
import os
import uuid
from typing import Protocol

from clinic_knowledge.config import KnowledgeSettings
from clinic_knowledge.constants import FOLDER

log = logging.getLogger("knowledge.storage")


def object_name(tenant_id: uuid.UUID, document_id: uuid.UUID, filename: str) -> str:
    extension = os.path.splitext(filename)[1].lower()
    return f"{FOLDER}/{tenant_id}/{document_id}/original{extension}"


def belongs_to(name: str, tenant_id: uuid.UUID) -> bool:
    return name.startswith(f"{FOLDER}/{tenant_id}/") and ".." not in name


class FileStore(Protocol):
    async def put(self, name: str, data: bytes, content_type: str) -> None: ...

    async def get(self, name: str) -> bytes | None:
        """The whole file, or None if it does not exist."""

    async def delete(self, name: str) -> None:
        """Remove the file. A file that is already gone is not an error."""


class GcsFileStore:
    def __init__(self, bucket: str, project: str | None = None):
        self._bucket_name, self._project, self._bucket = bucket, project, None

    def _bucket_handle(self):
        if self._bucket is None:
            from google.cloud import storage

            self._bucket = storage.Client(project=self._project or None).bucket(self._bucket_name)
        return self._bucket

    async def put(self, name: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            lambda: self._bucket_handle().blob(name).upload_from_string(data, content_type=content_type)
        )

    async def get(self, name: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        def download() -> bytes | None:
            try:
                return self._bucket_handle().blob(name).download_as_bytes()
            except NotFound:
                return None

        return await asyncio.to_thread(download)

    async def delete(self, name: str) -> None:
        from google.api_core.exceptions import NotFound

        def remove() -> None:
            try:
                self._bucket_handle().blob(name).delete()
            except NotFound:
                pass

        await asyncio.to_thread(remove)


def store_for(app, settings: KnowledgeSettings) -> FileStore | None:
    """The store for this app: one set by tests, else the configured bucket, else none (uploads unavailable)."""
    override = getattr(app.state, "knowledge_store", None)
    if override is not None:
        return override
    if settings.bucket:
        cached = getattr(app.state, "_knowledge_gcs_store", None)
        if cached is None:
            cached = app.state._knowledge_gcs_store = GcsFileStore(settings.bucket, settings.gcp_project or None)
        return cached
    return None
