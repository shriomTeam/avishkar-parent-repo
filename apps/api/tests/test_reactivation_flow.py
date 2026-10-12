"""End to end: client export -> dormant patients -> campaign -> SMS -> booking -> attribution."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from clinic_core.database import tenant_session
from clinic_db.models.engagement import Enrollment, Message
from clinic_db.models.ops import OutboxEvent
from clinic_db.models.reactivation import CampaignTarget
from clinic_engagement import run_due
from clinic_engagement.providers import SendResult
from clinic_worker.main import process_event


class FakeProvider:
    def __init__(self):
        self.sms: list[tuple[str, str]] = []

    async def send_sms(self, to, body):
        self.sms.append((to, body))
        return SendResult(ok=True, provider_message_id="fake")

    async def send_email(self, to, subject, body):
        return SendResult(ok=True, provider_message_id="fake")


async def _import_all(client, headers, sample):
    from clinic_integrations import suggest_mapping
    from clinic_integrations.sources import CsvSource

    for entity, name in (
        ("patient", "patients.csv"),
        ("appointment", "appointments.csv"),
        ("transaction", "transactions.csv"),
    ):
        mapping = suggest_mapping(entity, CsvSource(sample(name)).headers())
        r = await client.post(
            "/imports",
            headers=headers,
            data={"entity_type": entity, "source_system": "demo", "mapping": mapping.model_dump_json()},
            files={"file": (name, sample(name), "text/csv")},
        )
        assert r.status_code == 201, r.text
        assert r.json()["stats"]["errors"] == 0


async def _deliver_pending_events(tenant_id):
    """Do what the worker's relay + event consumer do, without Redis."""
    async with tenant_session(tenant_id) as s:
        events = (
            await s.scalars(select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id))
        ).all()
        for e in events:
            e.published_at = datetime.now(UTC)
    for e in events:
        job = SimpleNamespace(
            data={
                "id": e.id,
                "tenant_id": str(e.tenant_id),
                "type": e.event_type,
                "payload": e.payload,
                "created_at": e.created_at.isoformat(),
            }
        )
        await process_event(job, "token")


async def test_dormant_patients_get_reactivated_and_bookings_attributed(make_tenant, client, sample):
    tenant = await make_tenant(features=("reactivation",), settings={"booking_url": "https://book.test"})
    headers = {"X-Tenant-Id": str(tenant)}
    await _import_all(client, headers, sample)

    preview = (await client.get("/features/reactivation/preview", headers=headers)).json()
    assert preview["lapsed_days"] == 120  # med spa default
    assert preview["dormant_patients"] > 20
    assert preview["dormant_lifetime_value_cents"] > 0

    campaign = (await client.post("/features/reactivation/campaigns", headers=headers, json={})).json()
    assert campaign["stats"]["targets"] == preview["dormant_patients"]
    launched = (await client.post(f"/features/reactivation/campaigns/{campaign['id']}/launch", headers=headers)).json()
    assert launched["status"] == "running"

    # First step is due immediately; send at 2pm clinic time so quiet hours don't defer it.
    provider = FakeProvider()
    send_at = datetime.now(UTC).replace(hour=18, minute=0) + timedelta(days=1)
    async with tenant_session(tenant) as s:
        processed = await run_due(s, now=send_at, provider=provider, limit=10_000)
        blocked = (await s.scalars(select(Message).where(Message.status == "blocked"))).all()
    assert processed == preview["dormant_patients"]
    assert provider.sms and "https://book.test" in provider.sms[0][1]
    # Patients who said "No" to SMS in the export (recorded as a revoked consent) are never texted.
    assert blocked and {m.meta["reason"] for m in blocked} == {"opted_out"}
    assert len(provider.sms) + len(blocked) == processed

    # A texted patient books.
    async with tenant_session(tenant) as s:
        enr = await s.scalar(select(Enrollment).where(Enrollment.status == "active").limit(1))
    r = await client.post(
        "/appointments",
        headers=headers,
        json={
            "patient_id": str(enr.patient_id),
            "starts_at": (send_at + timedelta(days=3)).isoformat(),
            "booked_via": "sms",
        },
    )
    assert r.status_code == 201
    await _deliver_pending_events(tenant)

    async with tenant_session(tenant) as s:
        target = await s.scalar(select(CampaignTarget).where(CampaignTarget.patient_id == enr.patient_id))
        enr_after = await s.get(Enrollment, enr.id)
    assert target.status == "booked" and str(target.booked_appointment_id) == r.json()["id"]
    assert enr_after.status == "stopped" and enr_after.stop_reason == "booked"

    stats = (await client.get("/features/reactivation/campaigns", headers=headers)).json()[0]["stats"]
    assert stats["booked"] == 1


async def test_stop_keyword_revokes_consent_and_stops_sequence(make_tenant, client, sample):
    tenant = await make_tenant(features=("reactivation",))
    headers = {"X-Tenant-Id": str(tenant)}
    await _import_all(client, headers, sample)
    campaign = (await client.post("/features/reactivation/campaigns", headers=headers, json={})).json()
    await client.post(f"/features/reactivation/campaigns/{campaign['id']}/launch", headers=headers)
    async with tenant_session(tenant) as s:
        enr = await s.scalar(select(Enrollment).limit(1))

    r = await client.post(
        "/dev/inbound-message", headers=headers, json={"patient_id": str(enr.patient_id), "body": "STOP"}
    )
    assert r.status_code == 200
    await _deliver_pending_events(tenant)

    async with tenant_session(tenant) as s:
        enr_after = await s.get(Enrollment, enr.id)
    assert enr_after.status == "stopped" and enr_after.stop_reason == "opted_out"
