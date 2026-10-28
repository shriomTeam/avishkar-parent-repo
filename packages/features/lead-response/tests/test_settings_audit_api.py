"""What a save leaves in the audit log: names and versions, never values."""

import json
import logging

import pytest
from lr_api import URL, body, build_app, client_for, headers, put
from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import PracticeSettings
from clinic_db.models.ops import AuditLog
from clinic_lead_response.api.settings import _flat
from clinic_lead_response.settings_model import LeadResponseSettings

app = build_app()
MARKER = "Zebra-Quartz wording 4155550142"  # a fake phone number and fake words, easy to search for


@pytest.fixture
async def client():
    async with client_for(app) as c:
        yield c


async def _entries(tenant) -> list[AuditLog]:
    async with tenant_session(tenant) as s:
        return list(
            await s.scalars(select(AuditLog).where(AuditLog.action.like("lead_response.%")).order_by(AuditLog.id))
        )


async def test_a_save_writes_one_audit_row_with_names_and_versions(client, make_tenant):
    t = await make_tenant()
    await put(client, t, 0, body(holding_minutes=20, sla_minutes=60, ack_text=MARKER), staff="staff-9")
    await put(client, t, 1, body(holding_minutes=25, sla_minutes=60, ack_text=MARKER), staff="staff-9")
    first, second = await _entries(t)
    async with tenant_session(t) as s:
        ids = list(await s.scalars(select(PracticeSettings.id).order_by(PracticeSettings.version)))
    assert (first.action, first.actor_type, first.actor_id) == ("lead_response.settings.saved", "staff", "staff-9")
    assert (first.entity_type, first.entity_id) == ("lead_response_settings", ids[0])
    assert first.details == {
        "from_version": 0,
        "to_version": 1,
        "changed": ["ack_text", "holding_minutes", "sla_minutes"],
    }
    assert second.entity_id == ids[1]
    assert second.details == {"from_version": 1, "to_version": 2, "changed": ["holding_minutes"]}


async def test_no_value_reaches_the_audit_row(client, make_tenant):
    t = await make_tenant()
    await put(
        client,
        t,
        0,
        body(ack_text=MARKER, holding_minutes=22, business_hours={"mon": [{"start": "08:15", "end": "16:45"}]}),
    )
    (entry,) = await _entries(t)
    everything = json.dumps(
        [entry.action, entry.actor_id, entry.entity_type, str(entry.entity_id), entry.details], default=str
    )
    for value in ("Zebra", "4155550142", "08:15", "16:45", "22"):
        assert value not in everything.replace("to_version", ""), value
    assert set(entry.details) == {"from_version", "to_version", "changed"}
    assert "business_hours" in entry.details["changed"]  # named, never shown


async def test_no_audit_row_for_refused_stale_or_unchanged_saves(client, make_tenant):
    t = await make_tenant()
    await put(client, t, 0, body(holding_minutes=10))
    await put(client, t, 0, body(holding_minutes=11))  # stale
    await put(client, t, 1, body(holding_minutes=10))  # unchanged
    await put(client, t, 1, body(holding_minutes=4))  # invalid
    await put(client, t, 1, body(ai_enabled=True))  # AI gate
    await put(client, t, 1, body(holding_minutes=12), role="front_desk")  # role
    assert len(await _entries(t)) == 1


def test_capability_names_are_spread_out_and_the_rest_stay_whole():
    on = LeadResponseSettings.model_validate(
        {
            "capabilities": {"show_open_slots": True, "book_appointments": True},
            "business_hours": {"mon": [{"start": "09:00", "end": "17:00"}]},
        }
    )
    flat = _flat(on)
    assert flat["capabilities.book_appointments"] is True and "capabilities" not in flat
    assert "business_hours" in flat and "mon" not in flat  # hours stay one name


@pytest.mark.parametrize("rejected", ["invalid", "ai"])
async def test_nothing_is_logged_or_echoed_for_a_save(client, make_tenant, caplog, rejected):
    t = await make_tenant()
    payloads = {
        "invalid": body(ack_text=MARKER + " {merge}"),  # rejected: merge field
        "ai": body(ack_text=MARKER, ai_enabled=True),  # rejected: AI gate
    }
    with caplog.at_level(logging.DEBUG):
        response = await put(client, t, 0, payloads[rejected])
        ok = await put(client, t, 0, body(ack_text=MARKER))
        await client.get(URL, headers=headers(t))
    assert response.status_code == 422 and ok.status_code == 200
    assert "Zebra" not in response.text and "4155550142" not in response.text  # not echoed back by the 422
    assert "Zebra" not in caplog.text and "4155550142" not in caplog.text  # not logged by us or by the stack
