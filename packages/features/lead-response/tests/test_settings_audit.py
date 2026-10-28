import json

from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.lead_response import PracticeSettings
from clinic_db.models.ops import AuditLog
from clinic_lead_response.settings_audit import audit_settings_saved, changed_setting_names

SECRET_ACK = "Hi, this is Dr Smith's private wording 4155550123"


def _row(**kw):
    base = {
        "id": "x",
        "tenant_id": "t",
        "version": 1,
        "created_at": "now",
        "created_by": "u",
        "holding_minutes": 15,
        "sla_minutes": 30,
        "ack_text": "Hello",
        "send_mode": "draft",
    }
    return {**base, **kw}


def test_changed_names_lists_only_what_differs_and_skips_bookkeeping():
    before = _row()
    after = _row(version=2, created_by="other", holding_minutes=20, ack_text=SECRET_ACK)
    assert changed_setting_names(before, after) == ["ack_text", "holding_minutes"]


def test_the_first_version_counts_every_setting_as_changed():
    assert changed_setting_names(None, _row()) == ["ack_text", "holding_minutes", "send_mode", "sla_minutes"]


async def test_the_audit_row_holds_names_and_versions_never_values(make_tenant):
    t = await make_tenant()
    async with tenant_session(t) as s:
        row = PracticeSettings(tenant_id=t, version=2, ack_text=SECRET_ACK, holding_minutes=20, sla_minutes=60)
        s.add(row)
        await s.flush()
        await audit_settings_saved(
            s,
            actor_id="staff-1",
            settings_id=row.id,
            from_version=1,
            to_version=2,
            before=_row(),
            after=_row(version=2, ack_text=SECRET_ACK, holding_minutes=20, sla_minutes=60),
        )
    async with tenant_session(t) as s:
        entry = (
            (await s.execute(select(AuditLog).where(AuditLog.action == "lead_response.settings.saved"))).scalars().one()
        )
    assert entry.details == {
        "from_version": 1,
        "to_version": 2,
        "changed": ["ack_text", "holding_minutes", "sla_minutes"],
    }
    text = json.dumps(entry.details)
    assert "Smith" not in text and "4155550123" not in text and "20" not in text.replace("to_version", "")
