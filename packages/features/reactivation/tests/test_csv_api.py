"""POST /csv-analysis and its companions: the response, gating, limits, and that nothing is kept."""

import asyncio
import csv
import io
import json
import logging
import re
import tempfile
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import func, select, text

from clinic_core.api import require_feature
from clinic_core.auth.database import create_database
from clinic_core.database import system_session, tenant_session
from clinic_core.settings import Settings
from clinic_core.testing import create_test_tenant
from clinic_db.base import Base
from clinic_db.models.core import Patient
from clinic_db.models.ops import AuditLog
from clinic_db.models.reactivation import Run
from clinic_db.models.reactivation import Settings as SavedSettings
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.api import csv_analysis
from clinic_reactivation.csv_import import columns as cols
from clinic_reactivation.csv_import import parser
from clinic_reactivation.router import router

app = FastAPI()
app.state.settings = Settings(allow_dev_auth=True)
app.state.engine, app.state.session_factory = create_database(app.state.settings)
app.include_router(router)

gated = FastAPI()  # mounted the way the real API mounts every feature
gated.state.settings = app.state.settings
gated.state.engine, gated.state.session_factory = app.state.engine, app.state.session_factory
gated.include_router(router, prefix="/features/reactivation", dependencies=[Depends(require_feature("reactivation"))])

CANARY_EMAIL = "canary.person@canary-example.test"
CANARY_PHONE = "5559990000"
CANARY_NAME = "Zelda Canaryname"


def _h(tenant, role="owner"):
    return {"X-Tenant-Id": str(tenant), "X-Staff-Role": role}


def _csv_headers(tenant, role="owner"):
    return {**_h(tenant, role), "Content-Type": "text/csv"}


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def make_file(patients: int = 30, *, extra: dict | None = None) -> bytes:
    """Patients with three visits each, the last 200 to 700 days ago, so most are dormant."""
    names = ["patient_id", "patient_name", "email", "phone", "sms_consent", "visit_date", "line_kind",
             "service_name", "service_category", "amount", *(extra or {})]  # fmt: skip
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(names)
    today = datetime.now(UTC).date()
    for i in range(patients):
        last = today - timedelta(days=200 + (i * 17) % 500)
        for k in range(3):
            row = {
                "patient_id": f"P{i}", "patient_name": f"Person {i}", "email": f"p{i}@example.test",
                "phone": f"55501{i:05d}", "sms_consent": "yes",
                "visit_date": (last - timedelta(days=60 * k)).isoformat(),
                "line_kind": "service", "service_name": ["Botox", "Facial"][i % 2],
                "service_category": ["Injectables", "Facials"][i % 2], "amount": f"{150 + i * 7}.00",
                **(extra or {}),
            }  # fmt: skip
            w.writerow([row[n] for n in names])
    return out.getvalue().encode()


async def post(client, tenant, data, role="owner", **kw):
    return await client.post("/csv-analysis", content=data, headers=_csv_headers(tenant, role), **kw)


# --- the response ---------------------------------------------------------------------------------------------


async def test_a_file_is_analysed_and_returned_in_the_results_shape(client):
    tenant = await create_test_tenant()
    r = await post(client, tenant, make_file(40))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "csv" and body["rate_basis"] == "assumed" and body["settings_source"] == "defaults"
    assert body["counts"] == {"rows": 120, "patients": 40, "visit_days": 120}
    assert body["summary"]["patients_total"] == 40 and body["summary"]["dormant_count"] > 10
    assert body["summary"]["first_run"] is True
    assert body["quality"]["exclusion_flags_not_importable"] is True
    assert body["quality"]["currency_assumed"] == "USD"
    types = {t["type_key"]: t for t in body["types"]}
    assert types["unclassified"]["available"] is True and body["types"][-1]["type_key"] == "unclassified"
    assert all(
        t["rate_source"] == "assumed" for t in body["types"] if t["available"] and t["type_key"] != "unclassified"
    )
    assert types["consult_not_converted"]["available"] is False  # the file has no consult column
    first = body["patients"][0]
    assert first["external_id"].startswith("P") and first["display_name"].startswith("Person ")
    assert first["last_visit_day"] and first["points"]["best_time"]["reason"] == "needs_visit_times"
    assert [p["likelihood_score"] for p in body["patients"]] == sorted(
        (p["likelihood_score"] for p in body["patients"]), reverse=True
    )


async def test_saved_settings_are_used(client):
    tenant = await create_test_tenant()
    config = ReactivationSettings().model_dump(mode="json")
    config["dormant"]["min_days_since_visit"] = 3000
    config["dormant"]["default_rebooking_days"] = 3000
    async with tenant_session(tenant) as s:
        s.add(SavedSettings(tenant_id=tenant, version=3, config=config))
    body = (await post(client, tenant, make_file(20))).json()
    assert body["settings_source"] == "saved" and body["summary"]["dormant_count"] == 0


async def test_the_exclusion_warning_clears_only_when_both_flags_are_supplied(client):
    tenant = await create_test_tenant()
    both = make_file(10, extra={"do_not_contact": "no", "deceased": "no"})
    one = make_file(10, extra={"do_not_contact": "no"})
    assert (await post(client, tenant, both)).json()["quality"]["exclusion_flags_not_importable"] is False
    assert (await post(client, tenant, one)).json()["quality"]["exclusion_flags_not_importable"] is True
    flagged = make_file(10, extra={"do_not_contact": "yes", "deceased": "no"})
    body = (await post(client, tenant, flagged)).json()
    assert body["summary"]["patients_excluded"] == 10 and body["summary"]["dormant_count"] == 0


async def test_malformed_contacts_are_noted_not_rejected(client):
    tenant = await create_test_tenant()
    data = re.sub(rb"55501\d{5}", b"12", re.sub(rb"p\d+@example\.test", b"not-an-email", make_file(5)))
    body = (await post(client, tenant, data)).json()
    notes = {n["code"]: n["patients"] for n in body["notes"]}
    assert notes == {"email_treated_as_missing": 5, "phone_treated_as_missing": 5}


async def test_columns_template_and_data_status(client):
    tenant = await create_test_tenant()
    data = (await client.get("/csv-columns", headers=_h(tenant))).json()
    assert [c["name"] for c in data["columns"]] == list(cols.COLUMN_NAMES)
    assert data["limits"]["max_rows"] == parser.MAX_ROWS and any("amount of 0 or more" in n for n in data["notes"])
    r = await client.get("/csv-template", headers=_h(tenant))
    assert r.text == cols.template_csv() and "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("text/csv")
    assert (await client.get("/data-status", headers=_h(tenant))).json() == {
        "has_patients": False, "has_completed_run": False,
    }  # fmt: skip
    async with tenant_session(tenant) as s:
        s.add(Patient(tenant_id=tenant, first_name="A"))
    assert (await client.get("/data-status", headers=_h(tenant))).json()["has_patients"] is True
    other = await create_test_tenant()
    async with tenant_session(other) as s:
        s.add(Run(tenant_id=other, trigger="manual", status="failed", settings_version=0, settings={}))
        s.add(Run(tenant_id=other, trigger="manual", status="completed", settings_version=0, settings={}))
    assert (await client.get("/data-status", headers=_h(other))).json() == {
        "has_patients": False, "has_completed_run": True,
    }  # fmt: skip


# --- errors -----------------------------------------------------------------------------------------------------


async def test_an_invalid_file_is_rejected_with_a_list_and_no_cell_values(client):
    tenant = await create_test_tenant()
    rows = [f"P{i},{CANARY_NAME},2026-13-01,service,Botox,{CANARY_EMAIL},oops" for i in range(30)]
    data = (
        "patient_id,patient_name,visit_date,line_kind,service_name,email,amount\n" + "\n".join(rows) + "\n"
    ).encode()
    r = await post(client, tenant, data)
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "csv_invalid" and detail["total_errors"] == 60 and len(detail["errors"]) == 20
    assert {"row", "column", "reason"} == set(detail["errors"][0])
    assert CANARY_EMAIL not in r.text and CANARY_NAME not in r.text and "oops" not in r.text


@pytest.mark.parametrize(
    ("data", "code"),
    [(b"", "csv_empty"), (b"patient_id,visit_date,line_kind,amount\n", "csv_header_only"),
     (b"patient_id,visit_date,line_kind,amount\nP1,2026-01-01,membership,5.00\n", "csv_no_visits"),
     (b"\xff\xfe", "csv_bad_encoding"), (b"patient_id,nope\n", "csv_invalid_header")],
)  # fmt: skip
async def test_each_file_level_error_has_its_own_code(client, data, code):
    tenant = await create_test_tenant()
    r = await post(client, tenant, data)
    assert r.status_code == 422 and r.json()["detail"]["code"] == code and r.json()["detail"]["message"]


async def test_wrong_content_type(client):
    tenant = await create_test_tenant()
    for ctype in ("application/json", "multipart/form-data; boundary=x", "text/plain"):
        r = await client.post("/csv-analysis", content=b"x", headers={**_h(tenant), "Content-Type": ctype})
        assert (r.status_code, r.json()["detail"]["code"]) == (415, "csv_wrong_type")
    ok = await client.post(
        "/csv-analysis", content=make_file(5), headers={**_h(tenant), "Content-Type": "Text/CSV; charset=utf-8"}
    )
    assert ok.status_code == 200


async def test_size_limits_apply_to_the_declared_and_the_streamed_size(client, monkeypatch):
    tenant = await create_test_tenant()
    monkeypatch.setattr(parser, "MAX_BYTES", 500)
    r = await post(client, tenant, make_file(20))  # content-length is declared
    assert (r.status_code, r.json()["detail"]["code"]) == (413, "csv_too_large")

    async def chunks():  # no content-length: the stream itself is cut off
        data = make_file(20)
        for i in range(0, len(data), 100):
            yield data[i : i + 100]

    r = await client.post("/csv-analysis", content=chunks(), headers=_csv_headers(tenant))
    assert (r.status_code, r.json()["detail"]["code"]) == (413, "csv_too_large")
    monkeypatch.setattr(parser, "MAX_BYTES", 25 * 1024 * 1024)
    monkeypatch.setattr(parser, "MAX_ROWS", 50)
    assert (await post(client, tenant, make_file(20))).json()["detail"]["code"] == "csv_too_many_rows"
    monkeypatch.setattr(parser, "MAX_ROWS", 150_000)
    monkeypatch.setattr(parser, "MAX_PATIENTS", 5)
    r = await post(client, tenant, make_file(20))
    assert (r.status_code, r.json()["detail"]["code"]) == (413, "csv_too_many_patients")


async def test_a_busy_server_says_so(client):
    tenant = await create_test_tenant()
    for _ in range(csv_analysis.MAX_CONCURRENT):
        await csv_analysis._slots.acquire()
    try:
        r = await post(client, tenant, make_file(5))
        assert (r.status_code, r.json()["detail"]["code"]) == (429, "csv_busy")
    finally:
        for _ in range(csv_analysis.MAX_CONCURRENT):
            csv_analysis._slots.release()


async def test_a_timeout_returns_504_and_keeps_the_slot_until_the_thread_ends(client, monkeypatch):
    tenant = await create_test_tenant()
    real = csv_analysis.analyse_file

    def slow(*a, **kw):
        time.sleep(0.6)
        return real(*a, **kw)

    monkeypatch.setattr(csv_analysis, "analyse_file", slow)
    monkeypatch.setattr(csv_analysis, "TIMEOUT_SECONDS", 0.1)
    r = await post(client, tenant, make_file(5))
    assert (r.status_code, r.json()["detail"]["code"]) == (504, "csv_timed_out")
    assert not csv_analysis._slots.locked() or csv_analysis._slots._value < csv_analysis.MAX_CONCURRENT
    await asyncio.sleep(0.8)
    assert csv_analysis._slots._value == csv_analysis.MAX_CONCURRENT


async def test_an_engine_failure_returns_its_code_and_nothing_else(client, monkeypatch):
    tenant = await create_test_tenant()
    async with system_session() as s:
        await s.execute(text("UPDATE core.tenants SET timezone = 'Mars/Olympus' WHERE id = :t"), {"t": tenant})
    r = await post(client, tenant, make_file(5))
    assert (r.status_code, r.json()["detail"]["code"]) == (422, "bad_timezone")


# --- who may call it ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["front_desk", "provider", "consultant"])
async def test_only_owner_and_office_manager_can_import(client, role):
    tenant = await create_test_tenant()
    assert (await post(client, tenant, make_file(5), role=role)).status_code == 403
    assert (await client.get("/csv-columns", headers=_h(tenant, role))).status_code == 403
    assert (await client.get("/csv-template", headers=_h(tenant, role))).status_code == 403
    assert (await post(client, tenant, make_file(5), role="office_manager")).status_code == 200


async def test_front_desk_can_ask_whether_there_is_data(client):
    tenant = await create_test_tenant()
    assert (await client.get("/data-status", headers=_h(tenant, "front_desk"))).status_code == 200
    assert (await client.get("/data-status", headers=_h(tenant, "provider"))).status_code == 403


async def test_the_feature_must_be_enabled():
    with_feature = await create_test_tenant(("reactivation",))
    without = await create_test_tenant()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gated), base_url="http://test") as c:
        url = "/features/reactivation/csv-analysis"
        assert (await c.post(url, content=make_file(5), headers=_csv_headers(without))).status_code == 403
        assert (await c.post(url, content=make_file(5), headers=_csv_headers(with_feature))).status_code == 200
        assert (await c.get("/features/reactivation/csv-template", headers=_h(without))).status_code == 403


# --- nothing is kept -------------------------------------------------------------------------------------------------


async def _row_counts(tenant) -> dict[str, int]:
    """Every table that has a tenant_id, counted for this tenant, bypassing row-level security."""
    counts = {}
    async with system_session() as s:
        for table in Base.metadata.sorted_tables:
            if "tenant_id" in table.c:
                counts[table.fullname] = await s.scalar(
                    select(func.count()).select_from(table).where(table.c.tenant_id == tenant)
                )
    return counts


async def test_nothing_is_persisted_logged_or_written_to_disk(client, monkeypatch, caplog):
    tenant = await create_test_tenant(("reactivation",))
    async with tenant_session(tenant) as s:
        s.add(Patient(tenant_id=tenant, first_name="Existing"))
    before = await _row_counts(tenant)
    assert len(before) > 15

    def no_disk(*a, **kw):
        raise AssertionError("the CSV path must not create temporary files")

    for name in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp", "mkdtemp"):
        monkeypatch.setattr(tempfile, name, no_disk)

    data = make_file(40, extra={"membership_status": "active"}).replace(b"p0@example.test", CANARY_EMAIL.encode())
    data = data.replace(b"55501" + b"00000", CANARY_PHONE.encode()).replace(b"Person 0,", CANARY_NAME.encode() + b",")
    assert CANARY_EMAIL.encode() in data and CANARY_NAME.encode() in data
    caplog.set_level(logging.DEBUG)
    r = await post(client, tenant, data)
    assert r.status_code == 200
    bad = data.replace(b"150.00", b"oops", 1)
    assert (await post(client, tenant, bad)).status_code == 422

    after = await _row_counts(tenant)
    assert {k: after[k] - before[k] for k in after if after[k] != before[k]} == {"ops.audit_log": 1}
    async with tenant_session(tenant) as s:
        entry = (await s.scalars(select(AuditLog).where(AuditLog.action == "reactivation.csv_analysis.run"))).one()
    assert set(entry.details) == {"rows", "patients", "visit_days", "dormant_count", "bytes", "duration_ms"}
    assert entry.entity_id is None and all(isinstance(v, int) for v in entry.details.values())

    everything = json.dumps(r.json()) + " ".join(f"{x.getMessage()} {x.exc_text or ''}" for x in caplog.records)
    for secret in (CANARY_EMAIL, CANARY_PHONE):
        assert secret not in everything, "contact details must never be returned or logged"
    assert CANARY_NAME not in " ".join(x.getMessage() for x in caplog.records)
    # the display name is part of the result, but only because the person asked for patient names in the file
    assert CANARY_NAME in json.dumps(r.json())
