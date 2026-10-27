"""Where call recordings are kept: one private Cloud Storage bucket, one folder, one subfolder per clinic.

Recordings are patient audio. The service account can reach every clinic's files and database row-level
security does not cover storage, so object names are built here from the clinic and call ids and nowhere else.
Nothing that comes from a request ever becomes part of an object name.
"""

import asyncio
import logging
import uuid
from typing import Protocol

from clinic_voice_receptionist.config import VoiceSettings

log = logging.getLogger("voice.storage")

FOLDER = "voice-recordings"
CONTENT_TYPE = "audio/wav"


def recording_name(tenant_id: uuid.UUID, call_id: uuid.UUID) -> str:
    return f"{FOLDER}/{tenant_id}/{call_id}.wav"


def belongs_to(name: str, tenant_id: uuid.UUID) -> bool:
    return name.startswith(f"{FOLDER}/{tenant_id}/") and ".." not in name


class RecordingStore(Protocol):
    async def put(self, name: str, data: bytes) -> None: ...

    async def get(self, name: str) -> bytes | None:
        """The whole object, or None if it does not exist."""


class GcsRecordingStore:
    """Cloud Storage through the runtime's own credentials (the API's service account on Cloud Run)."""

    def __init__(self, bucket: str, project: str | None = None):
        self._bucket_name, self._project, self._bucket = bucket, project, None

    def _bucket_handle(self):
        if self._bucket is None:
            from google.cloud import storage  # imported on first use: only calls that record need it

            self._bucket = storage.Client(project=self._project or None).bucket(self._bucket_name)
        return self._bucket

    async def put(self, name: str, data: bytes) -> None:
        def upload() -> None:
            self._bucket_handle().blob(name).upload_from_string(data, content_type=CONTENT_TYPE)

        await asyncio.to_thread(upload)

    async def get(self, name: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        def download() -> bytes | None:
            try:
                return self._bucket_handle().blob(name).download_as_bytes()
            except NotFound:
                return None

        return await asyncio.to_thread(download)


def store_for(app, settings: VoiceSettings) -> RecordingStore | None:
    """The store for this app: one set by tests, else the configured bucket, else none (recording unavailable)."""
    override = getattr(app.state, "recording_store", None)
    if override is not None:
        return override
    if settings.recordings_bucket:
        cached = getattr(app.state, "_gcs_recording_store", None)
        if cached is None:
            cached = app.state._gcs_recording_store = GcsRecordingStore(
                settings.recordings_bucket, settings.gcp_project or None
            )
        return cached
    return None
