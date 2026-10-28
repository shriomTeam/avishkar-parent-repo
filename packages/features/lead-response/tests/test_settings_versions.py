import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import DEFAULT_ACK_TEXT, PracticeSettings


async def test_defaults_are_ai_off_draft_holding_15_sla_30(make_tenant):
    t = await make_tenant()
    async with tenant_session(t) as s:
        s.add(PracticeSettings(tenant_id=t, version=1))
    async with tenant_session(t) as s:
        # Read back through SQL. ack_text comes from the model's Python constant (the database has no default for it).
        row = (await s.execute(text("SELECT * FROM lead_response.practice_settings"))).mappings().one()
    assert row["ai_enabled"] is False
    assert row["send_mode"] == "draft"
    assert row["ai_active_mode"] == "always"
    assert row["holding_minutes"] == 15
    assert row["sla_minutes"] == 30
    assert row["escalation_role"] == "office_manager"
    assert row["ack_text"] == DEFAULT_ACK_TEXT
    assert row["context_fields"] == []
    assert row["capabilities"] and not any(row["capabilities"].values())


async def test_model_defaults_equal_database_defaults(make_tenant):
    # Version 1 takes the model's Python defaults, version 2 the database's own, and the two must agree.
    t = await make_tenant()
    async with tenant_session(t) as s:
        s.add(PracticeSettings(tenant_id=t, version=1))
        await s.execute(
            text(
                "INSERT INTO lead_response.practice_settings (tenant_id, version, ack_text) "
                "VALUES (CAST(:t AS uuid), 2, :ack)"
            ),
            {"t": str(t), "ack": DEFAULT_ACK_TEXT},
        )
    async with tenant_session(t) as s:
        rows = (
            (await s.execute(text("SELECT * FROM lead_response.practice_settings ORDER BY version"))).mappings().all()
        )
    skip = {"id", "version", "created_at"}
    assert {k: v for k, v in rows[0].items() if k not in skip} == {k: v for k, v in rows[1].items() if k not in skip}


async def test_the_ack_wording_has_no_database_default(make_tenant):
    t = await make_tenant()
    with pytest.raises(IntegrityError, match="ack_text"):
        async with tenant_session(t) as s:
            await s.execute(
                text("INSERT INTO lead_response.practice_settings (tenant_id, version) VALUES (CAST(:t AS uuid), 1)"),
                {"t": str(t)},
            )


async def test_a_new_version_does_not_overwrite_the_previous_one(make_tenant):
    t = await make_tenant()
    async with tenant_session(t) as s:
        s.add(PracticeSettings(tenant_id=t, version=1, holding_minutes=10, sla_minutes=40))
    async with tenant_session(t) as s:
        s.add(PracticeSettings(tenant_id=t, version=2, holding_minutes=20, sla_minutes=60))
    async with tenant_session(t) as s:
        rows = (await s.execute(select(PracticeSettings).order_by(PracticeSettings.version))).scalars().all()
    assert [(r.version, r.holding_minutes, r.sla_minutes) for r in rows] == [(1, 10, 40), (2, 20, 60)]


async def test_the_same_version_twice_fails(make_tenant):
    t = await make_tenant()
    async with tenant_session(t) as s:
        s.add(PracticeSettings(tenant_id=t, version=1))
    with pytest.raises(IntegrityError, match="uq_practice_settings"):
        async with tenant_session(t) as s:
            s.add(PracticeSettings(tenant_id=t, version=1))


@pytest.mark.parametrize(
    ("values", "constraint"),
    [
        ({"holding_minutes": 4}, "holding_range"),
        ({"holding_minutes": 61, "sla_minutes": 100}, "holding_range"),
        ({"sla_minutes": 9, "holding_minutes": 5}, "sla_range"),
        ({"sla_minutes": 241}, "sla_range"),
        ({"holding_minutes": 30, "sla_minutes": 30}, "sla_after_holding"),
        ({"holding_minutes": 40, "sla_minutes": 30}, "sla_after_holding"),
        ({"ai_active_mode": "overflow"}, "overflow_needs_minutes"),
    ],
)
async def test_the_database_rejects_out_of_range_timers(make_tenant, values, constraint):
    t = await make_tenant()
    with pytest.raises(IntegrityError, match=constraint):
        async with tenant_session(t) as s:
            s.add(PracticeSettings(tenant_id=t, version=1, **values))


async def test_boundary_timers_are_accepted(make_tenant):
    t = await make_tenant()
    async with tenant_session(t) as s:
        s.add(PracticeSettings(tenant_id=t, version=1, holding_minutes=5, sla_minutes=10))
        s.add(PracticeSettings(tenant_id=t, version=2, holding_minutes=60, sla_minutes=240))
        s.add(PracticeSettings(tenant_id=t, version=3, ai_active_mode="overflow", overflow_minutes=10))
