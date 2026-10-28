"""The Python defaults and the database column defaults must agree, column by column."""

import pytest
from lr_api import body, build_app, client_for, put
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import DEFAULT_ACK_TEXT
from clinic_lead_response.settings_model import LeadResponseSettings
from clinic_lead_response.settings_store import columns_from_settings

NOT_SETTINGS = {"id", "tenant_id", "version", "created_by", "created_at"}


async def test_every_database_default_equals_the_python_default(make_tenant):
    t = await make_tenant()
    # Only the columns that have no database default are supplied; every other column takes the database's own default.
    async with tenant_session(t) as s:
        await s.execute(
            text(
                "INSERT INTO lead_response.practice_settings (tenant_id, version, ack_text, created_by) "
                "VALUES (CAST(:t AS uuid), 1, :ack, 'staff-1')"
            ),
            {"t": str(t), "ack": DEFAULT_ACK_TEXT},
        )
        row = (await s.execute(text("SELECT * FROM lead_response.practice_settings"))).mappings().one()
    expected = {**columns_from_settings(LeadResponseSettings()), "context_fields": []}
    assert set(row) - NOT_SETTINGS == set(expected), "a column has no Python default (or the reverse)"
    for column, python_default in expected.items():
        assert row[column] == python_default, column


async def test_the_ack_text_has_no_database_default_so_every_insert_supplies_it(make_tenant):
    t = await make_tenant()
    with pytest.raises(IntegrityError, match="ack_text"):
        async with tenant_session(t) as s:
            await s.execute(
                text("INSERT INTO lead_response.practice_settings (tenant_id, version) VALUES (CAST(:t AS uuid), 1)"),
                {"t": str(t)},
            )


async def test_a_save_that_keeps_the_default_wording_still_writes_it(make_tenant):
    t = await make_tenant()
    async with client_for(build_app()) as client:
        assert (await put(client, t, 0, body(holding_minutes=10))).status_code == 200
    async with tenant_session(t) as s:
        assert await s.scalar(text("SELECT ack_text FROM lead_response.practice_settings")) == DEFAULT_ACK_TEXT


def test_the_columns_a_save_writes_are_all_real_columns():
    from clinic_db.models.lead_response import PracticeSettings

    real = {c.name for c in PracticeSettings.__table__.columns}
    assert set(columns_from_settings(LeadResponseSettings())) <= real
