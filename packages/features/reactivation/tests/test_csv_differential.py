"""The file path and the database path must give identical facts and an identical engine result.

The demo clinic's three sample files go through the real importer into a tenant. That data is then copied into
a second tenant whose patients, services and providers carry the ids the CSV builder derives (so every tie the
engine breaks by id is the same on both sides) and is made messier: consults, refunds, products, membership
payments, memberships in every status, consent history, do-not-contact and deceased flags, missing addresses
and an outlier. Two paths then read that second tenant:

  database: ``load_facts`` (the SQL)         CSV: rows read back from the tenant -> a file -> parse -> build

and ``analyse()`` runs on both with the same inputs.

What a file cannot carry is normalised on the database side and nowhere else: visit times, date of birth
(the copy has none), the appointment-status counters, and the number of membership rows (a file
has one per patient; only whether there is one matters). Two data shapes are avoided because a file expresses
them differently: a completed visit with no payment line, and a service payment with no visit.
"""

import asyncio
import csv
import io
import uuid
from dataclasses import fields, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from factories import Scene
from reference_facts import read_rows

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Appointment, Consent, Membership, Patient, Provider, Service, Transaction
from clinic_integrations import run_import, suggest_mapping
from clinic_integrations.sources import CsvSource
from clinic_reactivation.analysis.engine import analyse
from clinic_reactivation.analysis.exclusions import FlagValue, parse_flag
from clinic_reactivation.analysis.facts import PatientFacts, load_facts
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.csv_import.build import build_facts, derive_id
from clinic_reactivation.csv_import.columns import COLUMN_NAMES
from clinic_reactivation.csv_import.parser import parse_csv, service_key

SAMPLES = Path(__file__).parents[4] / "packages/integrations/samples/medspa"
AS_OF = datetime(2026, 10, 16, 4, 0, 1, tzinfo=UTC)  # a second past local midnight in New York
TZ = "America/New_York"
LOCAL = ZoneInfo(TZ)
TODAY = AS_OF.astimezone(LOCAL).date()
NS = uuid.uuid4()  # database ids are global and test rows stay behind, so each run derives its own


# --- 1. the demo data, through the real importer ---------------------------------------------------------------


async def import_demo() -> uuid.UUID:
    tenant = await create_test_tenant()
    for entity, filename in (
        ("patient", "patients.csv"),
        ("appointment", "appointments.csv"),
        ("transaction", "transactions.csv"),
    ):
        source = CsvSource(await asyncio.to_thread((SAMPLES / filename).read_bytes))
        async with tenant_session(tenant) as session:
            result = await run_import(
                session, source=source, source_system="demo_emr_export", entity_type=entity,
                mapping=suggest_mapping(entity, source.headers()), filename=filename, actor_id="test",
            )  # fmt: skip
            assert not result.errors[:3], result.errors[:3]
    return tenant


# --- 2. a copy with derived ids, made messier -------------------------------------------------------------------


async def copy_with_derived_ids(source: uuid.UUID) -> uuid.UUID:
    async with tenant_session(source) as s:
        rows = await read_rows(s)
    tenant = await create_test_tenant()
    sc = Scene(tenant)

    service_ids = {}
    for svc in rows["services"]:
        new = Service(
            id=derive_id("service", service_key(svc.name), NS), tenant_id=tenant, name=svc.name, category=svc.category
        )
        sc.services.append(new)
        service_ids[svc.id] = new
    consult = Service(id=derive_id("service", "consult", NS), tenant_id=tenant, name="Consult", category="Consult")
    sc.services.append(consult)
    provider_ids = {}
    for prov in rows["providers"]:
        new = Provider(id=derive_id("provider", service_key(prov.name), NS), tenant_id=tenant, name=prov.name)
        sc.providers.append(new)
        provider_ids[prov.id] = new

    patients = {}
    for i, old in enumerate(sorted(rows["patients"], key=lambda p: p.id)):
        attrs = {"ext": f"P{i:04d}"}  # the id the file will use for this patient
        if i % 11 == 3:
            attrs["do_not_contact"] = "yes"
        elif i % 7 == 2:
            attrs["do_not_contact"] = False
        if i % 13 == 5:
            attrs["deceased"] = True
        new = Patient(
            id=derive_id("patient", f"P{i:04d}", NS), tenant_id=tenant,
            first_name=old.first_name, last_name=old.last_name,
            email=None if i % 12 == 0 else old.email, phone=None if i % 14 == 0 else old.phone, attributes=attrs,
        )  # fmt: skip
        sc.patients.append(new)
        patients[old.id] = (i, new)

    appts = {}
    for old in sorted(rows["appointments"], key=lambda a: a.id):
        i, patient = patients[old.patient_id]
        new = Appointment(
            id=uuid.uuid4(), tenant_id=tenant, patient_id=patient.id, status=old.status, starts_at=old.starts_at,
            service_id=service_ids[old.service_id].id if old.service_id else None,
            provider_id=provider_ids[old.provider_id].id if old.provider_id else None, attributes={},
        )  # fmt: skip
        sc.appointments.append(new)
        appts[old.id] = new
    txns_by_appt: dict[uuid.UUID, Transaction] = {}
    for old in sorted(rows["transactions"], key=lambda t: t.id):
        i, patient = patients[old.patient_id]
        appt = appts.get(old.appointment_id)
        new = Transaction(
            id=uuid.uuid4(), tenant_id=tenant, patient_id=patient.id, appointment_id=appt.id if appt else None,
            amount_cents=old.amount_cents, kind=old.kind, occurred_at=old.occurred_at,
            service_id=service_ids[old.service_id].id if old.service_id else None,
        )  # fmt: skip
        sc.transactions.append(new)
        if appt:
            txns_by_appt[appt.id] = new
    for old in rows["consents"]:
        i, patient = patients[old.patient_id]
        sc.consents.append(
            Consent(
                id=uuid.uuid4(),
                tenant_id=tenant,
                patient_id=patient.id,
                kind=old.kind,
                granted=old.granted,
                source="test",
                recorded_at=old.recorded_at,
            )  # fmt: skip
        )

    def extra_txn(patient, amount, kind, when, appt=None, service_id=None):
        sc.transactions.append(
            Transaction(
                id=uuid.uuid4(),
                tenant_id=tenant,
                patient_id=patient.id,
                appointment_id=appt.id if appt else None,
                amount_cents=amount,
                kind=kind,
                occurred_at=when,
                service_id=service_id,
            )  # fmt: skip
        )

    done = {}
    for appt in sc.appointments:
        if appt.status == "completed" and appt.starts_at <= AS_OF:
            done.setdefault(appt.patient_id, []).append(appt)
    for i, patient in sorted(patients.values(), key=lambda x: x[0]):
        visits = sorted(done.get(patient.id, []), key=lambda a: a.starts_at)
        if visits and i % 7 == 4:  # the first visit was a consult
            first = visits[0]
            first.service_id = consult.id
            txn = txns_by_appt[first.id]
            txn.service_id = consult.id
            txn.amount_cents = 0 if i % 2 else 15000
        if visits and i % 6 == 1:  # a refund stored as a negative service amount, on the last visit
            last = visits[-1]
            extra_txn(patient, -2000, "service", last.starts_at, last, last.service_id)
        if visits and i % 4 == 2:  # a retail product with no service
            last = visits[-1]
            extra_txn(patient, 3500, "product", last.starts_at, last)
        if i % 9 == 4:
            extra_txn(patient, 9900, "membership", AS_OF - timedelta(days=20))
        if i % 15 == 2:
            extra_txn(patient, 20000, "package", AS_OF - timedelta(days=60))
        if visits and i == 20:  # an outlier far above 50x the median
            extra_txn(patient, 3_000_000, "product", visits[-1].starts_at, visits[-1])
        if i % 5 == 1:
            status = ["active", "cancelled", "lapsed", "expired"][(i // 5) % 4]
            sc.memberships.append(
                Membership(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    patient_id=patient.id,
                    plan_name="Plan",
                    status=status,
                    ends_at=None if status == "active" and i % 2 else date(2026, 1, 1) + timedelta(days=i),
                    recurring_amount_cents=9900 + i * 100,
                    prepaid_balance_cents=(i * 500) % 3000 if i % 2 else None,
                )  # fmt: skip
            )
            if i % 10 == 1:  # an older, second membership: the latest one decides the status
                sc.memberships.append(
                    Membership(
                        id=uuid.uuid4(),
                        tenant_id=tenant,
                        patient_id=patient.id,
                        plan_name="Old",
                        status="expired",
                        ends_at=date(2024, 1, 1),
                        recurring_amount_cents=5000,
                        prepaid_balance_cents=700,
                    )  # fmt: skip
                )
        if i % 3 == 0:
            sc.consents.append(
                Consent(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    patient_id=patient.id,
                    kind="email",
                    granted=i % 2 == 0,
                    source="test",
                    recorded_at=AS_OF - timedelta(days=90),
                )  # fmt: skip
            )
        if i % 10 == 3:  # consent history: the latest row wins
            sc.consents.append(
                Consent(
                    id=uuid.uuid4(),
                    tenant_id=tenant,
                    patient_id=patient.id,
                    kind="sms",
                    granted=False,
                    source="test",
                    recorded_at=AS_OF - timedelta(days=1),
                )  # fmt: skip
            )
    await sc.save()
    return tenant


# --- 3. the file, written from the copy's rows -------------------------------------------------------------------


def _money(cents: int) -> str:
    return str((Decimal(cents) / 100).quantize(Decimal("0.01")))


def _yes_no(value: bool | None) -> str:
    return "" if value is None else ("yes" if value else "no")


def _date(when: datetime) -> str:
    return when.astimezone(LOCAL).date().isoformat()


def _flag_cell(patient: Patient, key: str) -> str:
    return {FlagValue.TRUE: "yes", FlagValue.FALSE: "no"}.get(parse_flag(patient.attributes.get(key)), "")


def export_csv(rows: dict[str, list]) -> bytes:
    services = {s.id: s for s in rows["services"]}
    providers = {p.id: p for p in rows["providers"]}
    txns_of: dict[uuid.UUID, list[Transaction]] = {}
    for t in rows["transactions"]:
        txns_of.setdefault(t.patient_id, []).append(t)
    appts_of: dict[uuid.UUID, list[Appointment]] = {}
    for a in rows["appointments"]:
        appts_of.setdefault(a.patient_id, []).append(a)
    consents_of: dict[tuple[uuid.UUID, str], Consent] = {}
    for c in sorted(rows["consents"], key=lambda c: (c.recorded_at, c.id)):
        consents_of[(c.patient_id, c.kind)] = c
    memberships_of: dict[uuid.UUID, list[Membership]] = {}
    for m in rows["memberships"]:
        memberships_of.setdefault(m.patient_id, []).append(m)

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMN_NAMES)
    for patient in sorted(rows["patients"], key=lambda p: p.id):
        ext = patient.attributes["ext"]
        # patient-level cells, repeated on every row
        mships = sorted(
            memberships_of.get(patient.id, []),
            key=lambda m: (m.ends_at is not None, -(m.ends_at.toordinal() if m.ends_at else 0)),
        )
        latest = mships[0] if mships else None
        prepaid = sum(m.prepaid_balance_cents for m in mships if (m.prepaid_balance_cents or 0) > 0)
        booked = [a for a in appts_of.get(patient.id, []) if a.status == "booked" and a.starts_at >= AS_OF]
        sms, email = consents_of.get((patient.id, "sms")), consents_of.get((patient.id, "email"))
        fee = latest.recurring_amount_cents if latest else None
        cells = {
            "patient_id": ext,
            "patient_name": patient.first_name or "",
            "email": patient.email or "",
            "phone": patient.phone or "",
            "email_consent": _yes_no(email.granted if email else None),
            "sms_consent": _yes_no(sms.granted if sms else None),
            "membership_status": latest.status if latest else "",
            "membership_ended_on": latest.ends_at.isoformat() if latest and latest.ends_at else "",
            "membership_monthly_fee": "" if fee is None else _money(fee),
            "prepaid_balance": _money(prepaid) if latest else "",
            "next_appointment_date": _date(min(a.starts_at for a in booked)) if booked else "",
            "do_not_contact": _flag_cell(patient, "do_not_contact"),
            "deceased": _flag_cell(patient, "deceased"),
        }  # fmt: skip

        def emit(cells=cells, **line):
            writer.writerow([{**cells, **line}.get(name, "") for name in COLUMN_NAMES])

        visits = {a.id: a for a in appts_of.get(patient.id, []) if a.status == "completed" and a.starts_at <= AS_OF}
        lines = 0
        for t in sorted(txns_of.get(patient.id, []), key=lambda t: t.id):
            svc = services.get(t.service_id)
            appt = visits.get(t.appointment_id)
            line = {
                "line_kind": t.kind,
                "amount": _money(t.amount_cents),
                "service_name": svc.name if svc else "",
                "service_category": (svc.category or "") if svc else "",
            }
            if appt is not None:
                a_svc = services.get(appt.service_id)
                line.update(
                    visit_id=str(appt.id),
                    visit_date=_date(appt.starts_at),
                    visit_type="consult" if a_svc and (a_svc.category or "").lower() == "consult" else "treatment",
                    provider_name=providers[appt.provider_id].name if appt.provider_id else "",
                )  # fmt: skip
            else:  # a payment with no visit: dated by when it happened
                line["visit_date"] = _date(t.occurred_at)
            emit(**line)
            lines += 1
        assert lines or not visits, "every completed visit in this data has a payment"
        if not lines:  # a patient with nothing but a future booking still exists in the database
            emit(visit_date="2000-01-01", line_kind="other", amount="0.00")
    return out.getvalue().encode()


# --- 4. compare ----------------------------------------------------------------------------------------------------


def as_dict(f: PatientFacts) -> dict:
    d = {x.name: getattr(f, x.name) for x in fields(f) if x.name != "ingredients"}
    d["ingredients"] = tuple(getattr(f.ingredients, x.name) for x in fields(f.ingredients))
    return d


_RAW = {FlagValue.TRUE: True, FlagValue.FALSE: False, FlagValue.ABSENT: None}


def without_what_a_file_cannot_carry(f: PatientFacts) -> PatientFacts:
    return replace(
        f, visit_starts=(), date_of_birth=None, duplicate_appointments=0, completed_in_future=0,
        stale_booked_in_past=0, past_appointments=f.visit_count, unknown_appointment_status={},
        membership_rows=min(1, f.membership_rows),  # a file has one membership per patient
        do_not_contact_raw=_RAW[f.do_not_contact], deceased_raw=_RAW[f.deceased],  # the raw text is not kept
    )  # fmt: skip


async def test_file_and_database_paths_agree():
    copy = await copy_with_derived_ids(await import_demo())
    async with tenant_session(copy) as s:
        db_facts = await load_facts(s, AS_OF, TZ)
        rows = await read_rows(s)
    db_facts = sorted((without_what_a_file_cannot_carry(f) for f in db_facts), key=lambda f: f.patient_id.int)

    data = export_csv(rows)
    built = build_facts(parse_csv(data, today=TODAY), today=TODAY, namespace=NS)
    file_facts = sorted(built.facts, key=lambda f: f.patient_id.int)

    assert [f.patient_id for f in file_facts] == [f.patient_id for f in db_facts]
    for want, got in zip(db_facts, file_facts, strict=True):
        w, g = as_dict(want), as_dict(got)
        for key in w:
            assert g[key] == w[key], f"{key} differs for {want.patient_id}: file {g[key]!r}, database {w[key]!r}"

    # the data really exercised the rules
    assert sum(f.latest_consult_day is not None for f in db_facts) > 10
    assert sum(f.membership_rows > 0 for f in db_facts) > 10
    assert sum(f.do_not_contact is FlagValue.TRUE for f in db_facts) > 5
    assert sum(f.deceased is FlagValue.TRUE for f in db_facts) > 3
    assert sum(f.negative_ticket or f.ticket_total_cents != f.spend_cents for f in db_facts) > 10
    assert sum(f.outlier_transactions for f in db_facts) == 1
    assert sum(f.has_future_booking for f in db_facts) > 20

    settings = ReactivationSettings()
    names = {s.id: s.name for s in rows["services"]}
    assert built.service_names.items() <= names.items()
    args = (settings, {}, {}, None, AS_OF, TZ)
    want = analyse(db_facts, *args, service_names=names, verify_determinism=True)
    got = analyse(file_facts, *args, service_names=built.service_names, verify_determinism=True)
    assert got.canonical_json() == want.canonical_json()
    assert want.summary["dormant_count"] > 20
    assert want.summary["patients_excluded"] > 5
