import asyncio

import httpx
import pytest
from fastapi import FastAPI

from clinic_core.auth.database import create_database
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_knowledge import queue
from clinic_knowledge.testing import FakeEmbedder, MemoryFileStore
from clinic_voice_receptionist.knowledge.router import router as knowledge_router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.state.knowledge_store = MemoryFileStore()
app.state.knowledge_embedder = FakeEmbedder()
app.include_router(knowledge_router)

DOC = b"# Hours\n\nWe are open Monday to Friday, nine to five."


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _upload(client, tenant, name="hours.md", data=DOC, **form):
    return await client.post(
        "/inbound/knowledge/documents", files={"file": (name, data)}, data=form, headers=_h(tenant)
    )


async def _settle():
    while queue._running:
        await asyncio.gather(*list(queue._running))


async def test_upload_lists_as_processing_then_ready_and_delete_clears_it(client):
    tenant = await create_test_tenant()
    r = await _upload(client, tenant)
    assert r.status_code == 201 and r.json()["status"] == "uploaded"
    await _settle()
    docs = (await client.get("/inbound/knowledge/documents", headers=_h(tenant))).json()
    assert docs["enabled"] and [(d["filename"], d["status"], d["chunk_count"]) for d in docs["documents"]] == [
        ("hours.md", "ready", 1)
    ]
    doc_id = docs["documents"][0]["id"]
    assert (await client.delete(f"/inbound/knowledge/documents/{doc_id}", headers=_h(tenant))).status_code == 204
    assert (await client.get("/inbound/knowledge/documents", headers=_h(tenant))).json()["documents"] == []
    assert (await client.delete(f"/inbound/knowledge/documents/{doc_id}", headers=_h(tenant))).status_code == 404


async def test_duplicates_and_same_names_get_clear_answers(client):
    tenant = await create_test_tenant()
    assert (await _upload(client, tenant)).status_code == 201
    same = await _upload(client, tenant, "other.md")
    assert same.status_code == 409 and same.json()["detail"]["code"] == "same_file"
    named = await _upload(client, tenant, "hours.md", b"different words")
    assert named.status_code == 409 and named.json()["detail"]["code"] == "same_name"
    assert (await _upload(client, tenant, "hours.md", b"different words", same_name="keep")).status_code == 201
    await _settle()


async def test_bad_files_are_422_and_staff_without_rights_cannot_change_things(client):
    tenant = await create_test_tenant()
    assert (await _upload(client, tenant, "virus.exe", b"x")).status_code == 422
    r = await client.post(
        "/inbound/knowledge/documents", files={"file": ("a.txt", b"hello")}, headers=_h(tenant, "front_desk")
    )
    assert r.status_code == 403


async def test_other_clinics_see_nothing(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    await _upload(client, a)
    await _settle()
    assert (await client.get("/inbound/knowledge/documents", headers=_h(b))).json()["documents"] == []


async def test_search_endpoint_finds_uploaded_text_and_stays_inside_the_clinic(client):
    a, b = await create_test_tenant(), await create_test_tenant()
    await _upload(client, a, "hours.md", b"# Hours\n\nWe are open Monday to Friday, nine to five.")
    await _settle()
    r = await client.post("/inbound/knowledge/search", json={"query": "we are open Monday to Friday"}, headers=_h(a))
    assert r.status_code == 200 and r.json()["results"][0]["filename"] == "hours.md"
    other = await client.post(
        "/inbound/knowledge/search", json={"query": "we are open Monday to Friday"}, headers=_h(b)
    )
    assert other.json() == {"results": []}
    blank = await client.post("/inbound/knowledge/search", json={"query": "   "}, headers=_h(a))
    assert blank.status_code == 422
