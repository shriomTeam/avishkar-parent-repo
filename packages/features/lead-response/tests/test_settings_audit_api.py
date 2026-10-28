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
# Long, with letters no UUID or timestamp can contain, so finding it in a row or a log can never be a coincidence.
SENTINEL = "Zebra-Quartz sentinel wording that must never reach an audit row or a log"
# Every name a save may report as changed (the capabilities are spread out as capabilities.<name>).
SETTING_NAMES = set(_flat(LeadResponseSettings()))


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
    await put(client, t, 0, body(holding_minutes=20, sla_minutes=60, ack_text=SENTINEL), staff="staff-9")
    await put(client, t, 1, body(holding_minutes=25, sla_minutes=60, ack_text=SENTINEL), staff="staff-9")
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


def _leaves(value):
    """Every value at the bottom of nested dicts and lists."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)
    else:
        yield value


async def test_no_value_reaches_the_audit_row(client, make_tenant, caplog):
    t = await make_tenant()
    hours = {"mon": [{"start": "08:15", "end": "16:45"}]}
    with caplog.at_level(logging.DEBUG):
        saved = await put(
            client, t, 0, body(ack_text=SENTINEL, holding_minutes=22, business_hours=hours), staff="staff-7"
        )
    assert saved.status_code == 200
    async with tenant_session(t) as s:
        row_id = await s.scalar(select(PracticeSettings.id))
    (entry,) = await _entries(t)

    # The structure of the row, checked field by field. Nothing is searched for inside ids or JSON text.
    assert (entry.action, entry.actor_type, entry.actor_id, entry.entity_type) == (
        "lead_response.settings.saved",
        "staff",
        "staff-7",
        "lead_response_settings",
    )
    assert entry.entity_id == row_id
    assert set(entry.details) == {"from_version", "to_version", "changed"}
    assert (entry.details["from_version"], entry.details["to_version"]) == (0, 1)
    assert entry.details["changed"] == ["ack_text", "business_hours", "holding_minutes"]
    # Every value in the details is a setting name or a version number: no setting value (22, the hours, the wording).
    for leaf in _leaves(entry.details):
        is_version = type(leaf) is int and leaf in (0, 1)
        assert is_version or (isinstance(leaf, str) and leaf in SETTING_NAMES), "unexpected value in the audit details"

    # The one value we must never see is searched as a long sentinel, in the whole row and in the logs.
    whole_row = json.dumps(
        {column.name: getattr(entry, column.name) for column in AuditLog.__table__.columns}, default=str
    )
    assert SENTINEL not in whole_row
    assert SENTINEL not in caplog.text


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
        "invalid": body(ack_text=SENTINEL + " {merge}"),  # rejected: merge field
        "ai": body(ack_text=SENTINEL, ai_enabled=True),  # rejected: AI gate
    }
    with caplog.at_level(logging.DEBUG):
        response = await put(client, t, 0, payloads[rejected])
        ok = await put(client, t, 0, body(ack_text=SENTINEL))
        await client.get(URL, headers=headers(t))
    assert response.status_code == 422 and ok.status_code == 200
    assert SENTINEL not in response.text  # not echoed back by the 422
    assert SENTINEL not in caplog.text  # not logged by us or by the stack
