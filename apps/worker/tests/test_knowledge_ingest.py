import uuid

import httpx
import pytest

from clinic_core.database import tenant_session
from clinic_core.settings import get_settings
from clinic_core.testing import create_test_tenant
from clinic_db.models.knowledge import Document
from clinic_knowledge import service
from clinic_knowledge.config import KnowledgeSettings, get_knowledge_settings
from clinic_knowledge.testing import FakeEmbedder, MemoryFileStore
from clinic_worker.knowledge_ingest import app

URL = "/tasks/knowledge/ingest"


@pytest.fixture
async def client():
    app.state.knowledge_store = MemoryFileStore()
    app.state.knowledge_embedder = FakeEmbedder()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker") as c:
        yield c


@pytest.fixture(autouse=True)
def clean_settings():
    yield
    get_knowledge_settings.cache_clear()
    get_settings.cache_clear()


async def _document(tenant, data=b"# Hours\n\nWe are open nine to five."):
    async with tenant_session(tenant) as s:
        doc = await service.upload(
            s,
            tenant_id=tenant,
            staff_id=None,
            filename="hours.md",
            data=data,
            store=app.state.knowledge_store,
            settings=KnowledgeSettings(),
        )
        return doc.id


async def _status(tenant, document_id):
    async with tenant_session(tenant) as s:
        return (await s.get(Document, document_id)).status


async def test_a_task_reads_the_document_and_answers_200(client):
    tenant = await create_test_tenant()
    document_id = await _document(tenant)
    r = await client.post(URL, json={"tenant_id": str(tenant), "document_id": str(document_id)})
    assert r.status_code == 200 and r.json() == {"status": "ready"}
    assert await _status(tenant, document_id) == "ready"


async def test_a_task_for_a_deleted_document_is_done_not_retried(client):
    tenant = await create_test_tenant()
    r = await client.post(URL, json={"tenant_id": str(tenant), "document_id": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json() == {"status": "deleted"}


async def test_an_unreadable_file_ends_as_failed_with_200_so_it_is_not_retried_forever(client):
    tenant = await create_test_tenant()
    document_id = await _document(tenant, b"%PDF-1.4 nothing")
    async with tenant_session(tenant) as s:
        (await s.get(Document, document_id)).filename = "scan.pdf"
    r = await client.post(URL, json={"tenant_id": str(tenant), "document_id": str(document_id)})
    assert r.status_code == 200 and r.json() == {"status": "failed"}


async def test_a_malformed_task_is_rejected(client):
    assert (await client.post(URL, json={"tenant_id": "nope"})).status_code == 422


async def test_without_a_configured_audience_production_refuses_everything(client, monkeypatch):
    monkeypatch.setattr(
        "clinic_worker.knowledge_ingest.get_settings", lambda: type("S", (), {"app_env": "production"})()
    )
    tenant = await create_test_tenant()
    r = await client.post(URL, json={"tenant_id": str(tenant), "document_id": str(uuid.uuid4())})
    assert r.status_code == 503


async def test_with_an_audience_set_a_call_without_a_valid_token_is_refused(client, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TASKS_AUDIENCE", "https://ingest.example")
    monkeypatch.setenv("KNOWLEDGE_TASKS_INVOKER_EMAIL", "queue@x.iam.gserviceaccount.com")
    get_knowledge_settings.cache_clear()
    body = {"tenant_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4())}
    assert (await client.post(URL, json=body)).status_code == 401
    bad = await client.post(URL, json=body, headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401


async def test_a_valid_token_from_the_wrong_account_is_refused(client, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TASKS_AUDIENCE", "https://ingest.example")
    monkeypatch.setenv("KNOWLEDGE_TASKS_INVOKER_EMAIL", "queue@x.iam.gserviceaccount.com")
    get_knowledge_settings.cache_clear()
    from google.oauth2 import id_token

    monkeypatch.setattr(
        id_token, "verify_oauth2_token", lambda *a, **k: {"email": "someone@else.com", "email_verified": True}
    )
    body = {"tenant_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4())}
    r = await client.post(URL, json=body, headers={"Authorization": "Bearer t"})
    assert r.status_code == 403


async def test_a_valid_token_from_the_queue_account_is_accepted(client, monkeypatch):
    monkeypatch.setenv("KNOWLEDGE_TASKS_AUDIENCE", "https://ingest.example")
    monkeypatch.setenv("KNOWLEDGE_TASKS_INVOKER_EMAIL", "queue@x.iam.gserviceaccount.com")
    get_knowledge_settings.cache_clear()
    from google.oauth2 import id_token

    monkeypatch.setattr(
        id_token,
        "verify_oauth2_token",
        lambda *a, **k: {"email": "queue@x.iam.gserviceaccount.com", "email_verified": True},
    )
    tenant = await create_test_tenant()
    document_id = await _document(tenant)
    r = await client.post(
        URL,
        json={"tenant_id": str(tenant), "document_id": str(document_id)},
        headers={"Authorization": "Bearer t"},
    )
    assert r.status_code == 200
