"""Handing a document to the background ingestion.

Production puts a task on a Cloud Tasks queue, which calls the private ingest service (``apps/worker``) and retries
it until the document reaches a final state. Locally and in tests (no queue configured) the job runs in this process.
Callers enqueue only AFTER the transaction that created the document has committed, or the job could look for a row
that is not visible yet.
"""

import asyncio
import json
import logging
import uuid

from clinic_knowledge import ingest
from clinic_knowledge.config import KnowledgeSettings
from clinic_knowledge.embeddings import Embedder, VertexEmbedder
from clinic_knowledge.storage import FileStore

log = logging.getLogger("knowledge.queue")

INGEST_PATH = "/tasks/knowledge/ingest"
DISPATCH_DEADLINE_SECONDS = 600  # how long Cloud Tasks waits for one attempt; the ingest service allows the same

_running: set[asyncio.Task] = set()


def embedder_for(app, settings: KnowledgeSettings) -> Embedder:
    override = getattr(app.state, "knowledge_embedder", None)
    if override is not None:
        return override
    cached = getattr(app.state, "_knowledge_vertex_embedder", None)
    if cached is None:
        cached = app.state._knowledge_vertex_embedder = VertexEmbedder(settings)
    return cached


def uses_cloud_tasks(settings: KnowledgeSettings) -> bool:
    return bool(settings.tasks_queue and settings.ingest_url)


def _create_task(settings: KnowledgeSettings, tenant_id: uuid.UUID, document_id: uuid.UUID) -> None:
    from google.cloud import tasks_v2
    from google.protobuf import duration_pb2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(settings.gcp_project, settings.tasks_region, settings.tasks_queue)
    client.create_task(
        request={
            "parent": parent,
            "task": {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": settings.ingest_url.rstrip("/") + INGEST_PATH,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({"tenant_id": str(tenant_id), "document_id": str(document_id)}).encode(),
                    # Cloud Tasks signs the call as this service account; the ingest service checks the signature.
                    "oidc_token": {
                        "service_account_email": settings.tasks_invoker_email,
                        "audience": settings.tasks_audience or settings.ingest_url,
                    },
                },
                "dispatch_deadline": duration_pb2.Duration(seconds=DISPATCH_DEADLINE_SECONDS),
            },
        },
        timeout=10,
    )


async def enqueue(
    app,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    store: FileStore,
    settings: KnowledgeSettings,
    database_url: str | None = None,
) -> None:
    """Start ingestion. Never raises: if the job cannot be started the document is marked failed, so it shows."""
    if uses_cloud_tasks(settings):
        try:
            await asyncio.to_thread(_create_task, settings, tenant_id, document_id)
        except Exception:
            log.exception("could not queue ingestion of %s", document_id)
            await ingest.fail(
                tenant_id, document_id, "Processing could not be started. Please try again.", database_url
            )
        return

    embedder = embedder_for(app, settings)

    async def job() -> None:
        try:
            await ingest.run(
                tenant_id, document_id, store=store, embedder=embedder, settings=settings, database_url=database_url
            )
        except Exception:
            log.exception("ingestion of %s crashed", document_id)

    task = asyncio.get_running_loop().create_task(job())
    _running.add(task)  # keep a reference so the task is not collected mid-run
    task.add_done_callback(_running.discard)
