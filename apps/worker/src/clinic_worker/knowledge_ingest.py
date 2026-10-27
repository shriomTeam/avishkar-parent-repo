"""Knowledge-base ingestion worker: a small private HTTP service that Cloud Tasks calls, one request per document.

Cloud Tasks retries a request that does not answer 2xx, so a crash or a timeout is retried for free. We answer 2xx once
the document has reached a final state (ready, failed or duplicate), and 5xx only when it is still in progress.
In production the request must carry a Google-signed token from the configured service account; locally no token is
needed. Cloud Run scales this service to zero between uploads.
"""

import logging
import os
import uuid
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from clinic_core.database import dispose_engines, tenant_session
from clinic_core.settings import get_settings
from clinic_db.models.knowledge import Document
from clinic_knowledge import ingest
from clinic_knowledge.config import get_knowledge_settings
from clinic_knowledge.constants import IN_PROGRESS
from clinic_knowledge.queue import embedder_for
from clinic_knowledge.storage import store_for

log = logging.getLogger("clinic_worker.ingest")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await dispose_engines()


app = FastAPI(title="Knowledge ingest", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


class IngestTask(BaseModel):
    tenant_id: uuid.UUID
    document_id: uuid.UUID


def _check_caller(authorization: str | None) -> None:
    knowledge = get_knowledge_settings()
    if not knowledge.tasks_audience:
        if get_settings().app_env == "production":
            raise HTTPException(503, "ingest is not configured")
        return  # local run
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing token")
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(
            authorization.removeprefix("Bearer "), google_requests.Request(), audience=knowledge.tasks_audience
        )
    except ValueError:
        raise HTTPException(401, "invalid token") from None
    if not claims.get("email_verified") or claims.get("email") != knowledge.tasks_invoker_email:
        raise HTTPException(403, "caller not allowed")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/tasks/knowledge/ingest")
async def ingest_document(task: IngestTask, request: Request, authorization: str | None = Header(default=None)) -> dict:
    _check_caller(authorization)
    settings = get_knowledge_settings()
    store = store_for(request.app, settings)
    if store is None:
        raise HTTPException(503, "file storage is not set up")
    await ingest.run(
        task.tenant_id, task.document_id, store=store, embedder=embedder_for(request.app, settings), settings=settings
    )
    async with tenant_session(task.tenant_id) as session:
        document = await session.get(Document, task.document_id)
        status = document.status if document else "deleted"
    if status in IN_PROGRESS:
        raise HTTPException(503, "not finished yet")  # Cloud Tasks will call again
    return {"status": status}


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8081")))  # noqa: S104 - container port


if __name__ == "__main__":
    run()
