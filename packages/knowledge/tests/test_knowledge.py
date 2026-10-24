import uuid

import pytest
from sqlalchemy import func, select

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.knowledge import Chunk, Document
from clinic_knowledge import ingest, service
from clinic_knowledge.chunking import split
from clinic_knowledge.config import KnowledgeSettings
from clinic_knowledge.extract import Block, ExtractError, extract
from clinic_knowledge.testing import FakeEmbedder, MemoryFileStore

SETTINGS = KnowledgeSettings(max_documents=3, max_chunks=50, max_file_bytes=10_000)
HOURS = b"# Hours\n\nWe are open Monday to Friday, nine to five.\n\n# Parking\n\nFree parking is behind the building."


async def _add(tenant, store, name, data, **kw):
    async with tenant_session(tenant) as s:
        doc = await service.upload(
            s, tenant_id=tenant, staff_id=None, filename=name, data=data, store=store, settings=SETTINGS, **kw
        )
        return doc.id


async def _run(tenant, store, document_id, embedder=None):
    await ingest.run(tenant, document_id, store=store, embedder=embedder or FakeEmbedder(), settings=SETTINGS)


async def _doc(tenant, document_id):
    async with tenant_session(tenant) as s:
        return await s.get(Document, document_id)


# ---- pure parts --------------------------------------------------------------------------------------------


def test_text_is_read_with_headings():
    blocks = extract(HOURS, "hours.md")
    assert [b.heading for b in blocks] == ["Hours", "Parking"]


def test_unreadable_files_are_refused_in_plain_words():
    with pytest.raises(ExtractError):
        extract(b"   \n ", "empty.txt")
    with pytest.raises(ExtractError):
        extract(b"not a pdf", "broken.pdf")


def test_long_text_is_split_with_some_repeated_between_passages():
    sentence = "The clinic offers a wide range of treatments for every patient. "
    passages = split([Block("Services", sentence * 200)], target=100, overlap=20)
    assert len(passages) > 3
    assert all(p.heading == "Services" and p.tokens <= 130 for p in passages)


# ---- upload ------------------------------------------------------------------------------------------------


async def test_upload_stores_the_file_under_the_clinic_and_starts_as_uploaded():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    doc = await _doc(tenant, await _add(tenant, store, "hours.md", HOURS))
    assert doc.status == "uploaded" and doc.object_name.startswith(f"knowledge-base/{tenant}/")
    assert store.objects[doc.object_name] == HOURS


@pytest.mark.parametrize(
    "name,data,message",
    [("a.exe", b"x", "Only PDF"), ("a.txt", b"", "empty"), ("a.txt", b"x" * 10_001, "up to")],
)
async def test_bad_files_are_refused(name, data, message):
    tenant = await create_test_tenant()
    with pytest.raises(service.KnowledgeError, match=message):
        await _add(tenant, MemoryFileStore(), name, data)


async def test_path_tricks_in_a_filename_are_dropped():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    doc = await _doc(tenant, await _add(tenant, store, "../../etc/passwd.txt", b"hello there"))
    assert doc.filename == "passwd.txt" and ".." not in doc.object_name


async def test_the_same_file_twice_is_refused():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    await _add(tenant, store, "hours.md", HOURS)
    with pytest.raises(service.SameFile):
        await _add(tenant, store, "copy-of-hours.md", HOURS)


async def test_same_name_asks_then_replace_or_keep_both():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    first = await _add(tenant, store, "hours.md", HOURS)
    with pytest.raises(service.SameName):
        await _add(tenant, store, "Hours.md", b"New opening times: every day.")
    replacing = await _doc(tenant, await _add(tenant, store, "hours.md", b"New hours text", same_name="replace"))
    assert replacing.replaces_id == first
    keeping = await _doc(tenant, await _add(tenant, store, "hours.md", b"Another version", same_name="keep"))
    assert keeping.replaces_id is None


async def test_a_clinic_cannot_go_over_its_document_limit():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    for i in range(3):
        await _add(tenant, store, f"d{i}.txt", f"document number {i}".encode())
    with pytest.raises(service.KnowledgeError, match="up to 3"):
        await _add(tenant, store, "d4.txt", b"one too many")


# ---- ingest ------------------------------------------------------------------------------------------------


async def test_ingest_makes_passages_and_marks_the_document_ready():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _add(tenant, store, "hours.md", HOURS)
    await _run(tenant, store, document_id)
    doc = await _doc(tenant, document_id)
    assert doc.status == "ready" and doc.chunk_count == 2 and doc.text_hash
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(Chunk).order_by(Chunk.ordinal))).all()
    assert [c.heading for c in rows] == ["Hours", "Parking"] and len(rows[0].embedding) == 768


async def test_running_a_finished_document_again_changes_nothing():
    tenant, store, embedder = await create_test_tenant(), MemoryFileStore(), FakeEmbedder()
    document_id = await _add(tenant, store, "hours.md", HOURS)
    await _run(tenant, store, document_id, embedder)
    await _run(tenant, store, document_id, embedder)
    assert len(embedder.calls) == 1


async def test_same_text_in_a_different_file_is_marked_duplicate_and_adds_no_passages():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    first = await _add(tenant, store, "hours.md", HOURS)
    await _run(tenant, store, first)
    second = await _add(tenant, store, "hours-copy.md", HOURS + b"\n\n  ")  # other bytes, same words
    await _run(tenant, store, second)
    doc = await _doc(tenant, second)
    assert doc.status == "duplicate" and doc.duplicate_of_id == first and "hours.md" in doc.error
    async with tenant_session(tenant) as s:
        assert await s.scalar(select(func.count()).select_from(Chunk).where(Chunk.document_id == second)) == 0


async def test_a_failure_is_recorded_in_words_and_can_be_retried():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _add(tenant, store, "hours.md", HOURS)
    await _run(tenant, store, document_id, FakeEmbedder(fail_times=1))
    doc = await _doc(tenant, document_id)
    assert doc.status == "failed" and "not available" in doc.error
    async with tenant_session(tenant) as s:
        await service.retry(s, document_id)
    await _run(tenant, store, document_id)
    assert (await _doc(tenant, document_id)).status == "ready"


async def test_an_unreadable_file_fails_with_a_clear_reason():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _add(tenant, store, "scan.pdf", b"%PDF-1.4 nothing here")
    await _run(tenant, store, document_id)
    doc = await _doc(tenant, document_id)
    assert doc.status == "failed" and doc.error


async def test_replacing_swaps_the_old_document_for_the_new_one_when_ready():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    old = await _add(tenant, store, "hours.md", HOURS)
    await _run(tenant, store, old)
    old_object = (await _doc(tenant, old)).object_name
    new = await _add(tenant, store, "hours.md", b"# Hours\n\nNow open on Saturdays too.", same_name="replace")
    await _run(tenant, store, new)
    assert await _doc(tenant, old) is None and old_object not in store.objects
    assert (await _doc(tenant, new)).status == "ready"


async def test_a_clinic_over_its_passage_limit_is_told_so():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    big = "\n\n".join(f"Paragraph {i}. " + "Some detail about the clinic. " * 60 for i in range(60)).encode()
    settings = KnowledgeSettings(max_chunks=5, max_file_bytes=1_000_000)
    async with tenant_session(tenant) as s:
        doc = await service.upload(
            s, tenant_id=tenant, staff_id=None, filename="big.txt", data=big, store=store, settings=settings
        )
    await ingest.run(tenant, doc.id, store=store, embedder=FakeEmbedder(), settings=settings)
    got = await _doc(tenant, doc.id)
    assert got.status == "failed" and "size limit" in got.error


# ---- delete and isolation ------------------------------------------------------------------------------------


async def test_deleting_removes_the_passages_and_the_stored_file():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _add(tenant, store, "hours.md", HOURS)
    await _run(tenant, store, document_id)
    name = (await _doc(tenant, document_id)).object_name
    async with tenant_session(tenant) as s:
        await service.delete(s, document_id, store)
    assert name not in store.objects
    async with tenant_session(tenant) as s:
        assert await s.scalar(select(func.count()).select_from(Chunk)) == 0


async def test_one_clinic_never_sees_or_deletes_another_clinics_documents():
    a, b, store = await create_test_tenant(), await create_test_tenant(), MemoryFileStore()
    document_id = await _add(a, store, "hours.md", HOURS)
    await _run(a, store, document_id)
    async with tenant_session(b) as s:
        assert await service.list_documents(s) == []
        with pytest.raises(service.NotFound):
            await service.delete(s, document_id, store)
    # the other clinic can upload the very same file: duplicates are checked per clinic
    await _add(b, store, "hours.md", HOURS)


# ---- search --------------------------------------------------------------------------------------------------

from clinic_knowledge import search as finder  # noqa: E402

MENU = (
    b"# Botox\n\nBotox treatment costs two hundred dollars per area and lasts about three months.\n\n"
    b"# Parking\n\nFree parking is available behind the building, entrance on Maple Street.\n\n"
    b"# Cancellation\n\nPlease cancel at least twenty four hours before your appointment to avoid a fee."
)


async def _ready(tenant, store, name, data):
    document_id = await _add(tenant, store, name, data)
    await _run(tenant, store, document_id)
    return document_id


async def _find(tenant, query, **kw):
    async with tenant_session(tenant) as s:
        return await finder.search(s, query, embedder=FakeEmbedder(), **kw)


async def test_search_finds_the_passage_that_answers_the_question():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    await _ready(tenant, store, "menu.md", MENU)
    hits = await _find(tenant, "botox treatment costs per area")
    assert hits and hits[0].heading == "Botox" and hits[0].filename == "menu.md"


async def test_search_says_nothing_when_nothing_is_relevant():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    await _ready(tenant, store, "menu.md", MENU)
    assert await _find(tenant, "quantum chromodynamics lattice") == []
    assert await _find(tenant, "   ") == []


async def test_search_is_limited_to_one_clinic():
    a, b, store = await create_test_tenant(), await create_test_tenant(), MemoryFileStore()
    await _ready(a, store, "menu.md", MENU)
    assert await _find(b, "botox treatment costs per area") == []


async def test_search_with_odd_characters_is_safe():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    await _ready(tenant, store, "menu.md", MENU)
    for query in ["botox'; DROP TABLE x;--", "botox & | ! ( ) :*", "💉 botox cost?"]:
        await _find(tenant, query)


async def test_deleted_documents_stop_appearing_in_search():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _ready(tenant, store, "menu.md", MENU)
    assert await _find(tenant, "free parking is available behind the building")
    async with tenant_session(tenant) as s:
        await service.delete(s, document_id, store)
    assert await _find(tenant, "free parking is available behind the building") == []


async def test_passages_already_kept_in_another_document_are_not_stored_again():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    first = await _ready(tenant, store, "menu.md", MENU)
    partly = MENU.split(b"\n\n# Cancellation")[0] + b"\n\n# Pets\n\nSmall dogs are welcome in the waiting room."
    second = await _ready(tenant, store, "mixed.md", partly)
    async with tenant_session(tenant) as s:
        rows = (await s.scalars(select(Chunk).where(Chunk.document_id == second))).all()
    assert [c.heading for c in rows] == ["Pets"]
    assert (await _doc(tenant, second)).chunk_count == 1 and first != second


async def test_a_file_made_only_of_known_passages_is_marked_duplicate():
    tenant, store = await create_test_tenant(), MemoryFileStore()
    first = await _ready(tenant, store, "menu.md", MENU)
    subset = MENU.split(b"\n\n# Cancellation")[0]
    second = await _ready(tenant, store, "part.md", subset)
    doc = await _doc(tenant, second)
    assert doc.status == "duplicate" and doc.duplicate_of_id == first


# ---- queue ---------------------------------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from clinic_knowledge import queue  # noqa: E402

CLOUD = KnowledgeSettings(
    tasks_queue="ingest", tasks_region="us-east1", ingest_url="https://ingest.example", tasks_invoker_email="q@x.iam"
)


async def test_with_a_queue_configured_a_task_is_created_and_nothing_runs_in_process(monkeypatch):
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _add(tenant, store, "hours.md", HOURS)
    created = []
    monkeypatch.setattr(queue, "_create_task", lambda settings, t, d: created.append((t, d)))
    await queue.enqueue(SimpleNamespace(state=SimpleNamespace()), tenant, document_id, store, CLOUD)
    assert created == [(tenant, document_id)]
    assert (await _doc(tenant, document_id)).status == "uploaded"  # the worker, not this process, will read it


async def test_if_the_task_cannot_be_created_the_document_shows_as_failed(monkeypatch):
    tenant, store = await create_test_tenant(), MemoryFileStore()
    document_id = await _add(tenant, store, "hours.md", HOURS)

    def broken(settings, t, d):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(queue, "_create_task", broken)
    await queue.enqueue(SimpleNamespace(state=SimpleNamespace()), tenant, document_id, store, CLOUD)
    doc = await _doc(tenant, document_id)
    assert doc.status == "failed" and "could not be started" in doc.error


def test_the_task_is_signed_for_the_ingest_service(monkeypatch):
    from google.cloud import tasks_v2

    sent = {}

    class FakeClient:
        def queue_path(self, project, region, name):
            return f"projects/{project}/locations/{region}/queues/{name}"

        def create_task(self, request, timeout):
            sent.update(request)

    monkeypatch.setattr(tasks_v2, "CloudTasksClient", FakeClient)
    tenant, document_id = uuid.uuid4(), uuid.uuid4()
    queue._create_task(CLOUD.model_copy(update={"gcp_project": "p"}), tenant, document_id)
    http = sent["task"]["http_request"]
    assert sent["parent"] == "projects/p/locations/us-east1/queues/ingest"
    assert http["url"] == "https://ingest.example/tasks/knowledge/ingest"
    assert http["oidc_token"] == {"service_account_email": "q@x.iam", "audience": "https://ingest.example"}
    assert str(document_id) in http["body"].decode()
