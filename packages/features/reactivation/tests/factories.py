"""Builds tenants full of the anomalies in docs/analysis-engine-spec.md section 7 (item 2), plus
what the demo data lacks: refunds stored as negative service amounts, consults with and without a
quoted plan, memberships in every status, exclusion flags, staff.

Impossible-by-schema anomalies are not built: NULL amounts and naive timestamps (columns forbid
them). A zero interval is a settings value, not core data, so it is not built here.
"""

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Appointment, Consent, Membership, Patient, Provider, Service, Staff, Transaction

NOW = datetime(2026, 6, 1, 15, tzinfo=UTC)  # 11:00 on 2026-06-01 in New York
TZ = "America/New_York"


def at(y: int, m: int, d: int, hour: int = 14, minute: int = 0) -> datetime:
    return datetime(y, m, d, hour, minute, tzinfo=UTC)


@dataclass
class Scene:
    """Collects rows with explicit ids, then writes them in dependency order."""

    tenant: uuid.UUID
    staff: list[Staff] = field(default_factory=list)
    providers: list[Provider] = field(default_factory=list)
    services: list[Service] = field(default_factory=list)
    patients: list[Patient] = field(default_factory=list)
    appointments: list[Appointment] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    memberships: list[Membership] = field(default_factory=list)
    consents: list[Consent] = field(default_factory=list)
    ids: dict[str, uuid.UUID] = field(default_factory=dict)

    def _id(self) -> uuid.UUID:
        # Random ids on purpose: the data is deterministic (seeded rng) but rows from earlier
        # runs stay in the database, so fixed ids would collide on a second run.
        return uuid.uuid4()

    def service(self, name: str, category: str | None) -> Service:
        row = Service(id=self._id(), tenant_id=self.tenant, name=name, category=category)
        self.services.append(row)
        self.ids[f"service:{name}"] = row.id
        return row

    def provider(self, name: str, *, staff_active: bool | None) -> Provider:
        staff_id = None
        if staff_active is not None:
            member = Staff(
                id=self._id(),
                tenant_id=self.tenant,
                email=f"{name}-{self._id()}@x.test",
                name=name,
                role="provider",
                active=staff_active,
            )
            self.staff.append(member)
            staff_id = member.id
        row = Provider(id=self._id(), tenant_id=self.tenant, name=name, staff_id=staff_id)
        self.providers.append(row)
        self.ids[f"provider:{name}"] = row.id
        return row

    def patient(self, name: str, **kw: Any) -> Patient:
        kw.setdefault("phone", "+15550001111")
        kw.setdefault("email", f"{name}@example.test")
        row = Patient(id=self._id(), tenant_id=self.tenant, first_name=name, **kw)
        self.patients.append(row)
        self.ids[name] = row.id
        return row

    def appt(
        self,
        patient: Patient,
        status: str,
        starts: datetime,
        service: Service | None = None,
        provider: Provider | None = None,
        attrs: dict | None = None,
    ) -> Appointment:
        row = Appointment(
            id=self._id(),
            tenant_id=self.tenant,
            patient_id=patient.id,
            status=status,
            starts_at=starts,
            service_id=service.id if service else None,
            provider_id=provider.id if provider else None,
            attributes=attrs or {},
        )
        self.appointments.append(row)
        return row

    def txn(
        self,
        patient: Patient,
        amount: int,
        *,
        kind: str = "service",
        appt: Appointment | None = None,
        service: Service | None = None,
        when: datetime | None = None,
    ) -> Transaction:
        row = Transaction(
            id=self._id(),
            tenant_id=self.tenant,
            patient_id=patient.id,
            amount_cents=amount,
            kind=kind,
            appointment_id=appt.id if appt else None,
            service_id=service.id if service else None,
            occurred_at=when or (appt.starts_at if appt else NOW - timedelta(days=30)),
        )
        self.transactions.append(row)
        return row

    def membership(
        self,
        patient: Patient,
        status: str,
        *,
        ends: date | None = None,
        fee: int | None = None,
        prepaid: int | None = None,
        updated: datetime | None = None,
    ) -> Membership:
        row = Membership(
            id=self._id(),
            tenant_id=self.tenant,
            patient_id=patient.id,
            plan_name="Plan",
            status=status,
            ends_at=ends,
            recurring_amount_cents=fee,
            prepaid_balance_cents=prepaid,
        )
        if updated is not None:
            row.updated_at = updated
        self.memberships.append(row)
        return row

    def consent(self, patient: Patient, kind: str, granted: bool, when: datetime | None = None) -> Consent:
        row = Consent(
            id=self._id(),
            tenant_id=self.tenant,
            patient_id=patient.id,
            kind=kind,
            granted=granted,
            source="test",
            recorded_at=when or (NOW - timedelta(days=100)),
        )
        self.consents.append(row)
        return row

    async def save(self) -> uuid.UUID:
        async with tenant_session(self.tenant) as s:
            for group in (self.staff, self.services):
                s.add_all(group)
            await s.flush()
            s.add_all(self.providers)
            s.add_all(self.patients)
            await s.flush()
            s.add_all(self.appointments)
            s.add_all(self.memberships)
            s.add_all(self.consents)
            await s.flush()
            s.add_all(self.transactions)
        return self.tenant


@dataclass
class Messy:
    tenant: uuid.UUID
    ids: dict[str, uuid.UUID]


async def build_messy_tenant(*, with_memberships: bool = True, settings: dict | None = None) -> Messy:
    tenant = await create_test_tenant(settings=settings)
    sc = Scene(tenant)
    botox = sc.service("Botox", "Injectables")
    facial = sc.service("Facial", " Facials ")
    consult = sc.service("Consult", "Consult")  # matched case-insensitively, trimmed
    sc.service("Unsorted", None)
    dr_active = sc.provider("Dr Active", staff_active=True)
    dr_gone = sc.provider("Dr Gone", staff_active=False)
    dr_free = sc.provider("Dr Free", staff_active=None)

    # --- the ordinary patient ---------------------------------------------------------------
    p = sc.patient("regular")
    for day in (at(2026, 4, 2), at(2026, 2, 3), at(2025, 12, 4)):
        a = sc.appt(p, "completed", day, botox, dr_active)
        sc.txn(p, 40000, appt=a, service=botox)
    sc.consent(p, "sms", True)

    # --- appointment anomalies --------------------------------------------------------------
    p = sc.patient("duplicate_appts")
    first = None
    for _ in range(3):
        a = sc.appt(p, "completed", at(2026, 3, 10), botox)
        first = first or a
    sc.txn(p, 30000, appt=first, service=botox)

    p = sc.patient("future_completed")
    sc.appt(p, "completed", at(2026, 2, 20), botox)
    sc.appt(p, "completed", at(2026, 6, 6), botox)

    p = sc.patient("stale_booked")
    sc.appt(p, "completed", at(2026, 1, 15), botox)
    sc.appt(p, "booked", at(2026, 5, 29), botox)

    p = sc.patient("future_booking")
    sc.appt(p, "completed", at(2026, 3, 1), botox)
    sc.appt(p, "booked", at(2026, 6, 10), botox)

    p = sc.patient("booking_at_now")
    sc.appt(p, "completed", at(2026, 3, 1), botox)
    sc.appt(p, "booked", NOW, botox)

    p = sc.patient("unknown_status")
    sc.appt(p, "completed", at(2026, 3, 5), botox)
    sc.appt(p, "rescheduled", at(2026, 3, 6), botox)
    sc.appt(p, "rescheduled", at(2026, 3, 7), botox)
    sc.appt(p, "weird", at(2026, 3, 8), botox)

    p = sc.patient("no_completed")
    sc.appt(p, "cancelled", at(2026, 4, 1), botox)
    sc.appt(p, "no_show", at(2026, 4, 8), botox)

    sc.patient("empty")

    # --- money ------------------------------------------------------------------------------
    p = sc.patient("refund_big")
    a = sc.appt(p, "completed", at(2026, 4, 4))
    sc.txn(p, 10000, appt=a)
    sc.txn(p, -25000, when=at(2026, 4, 20))

    p = sc.patient("refund_netting")
    a1 = sc.appt(p, "completed", at(2026, 4, 10), botox)
    a2 = sc.appt(p, "completed", at(2026, 4, 20), botox)
    sc.txn(p, 50000, appt=a1, service=botox)
    sc.txn(p, 10000, kind="product", appt=a1)
    sc.txn(p, -20000, appt=a2, service=botox)

    p = sc.patient("membership_neg")
    a = sc.appt(p, "completed", at(2026, 4, 5), botox)
    sc.txn(p, 30000, appt=a, service=botox)
    sc.txn(p, 9900, kind="membership", when=at(2026, 4, 5))
    sc.txn(p, -4900, kind="membership", when=at(2026, 4, 6))

    p = sc.patient("package_buyer")
    a = sc.appt(p, "completed", at(2026, 4, 6), botox)
    sc.txn(p, 20000, appt=a, service=botox)
    sc.txn(p, 150000, kind="package", when=at(2026, 4, 6))

    p = sc.patient("tx_by_day")
    a_first = sc.appt(p, "completed", at(2026, 3, 3), botox)
    sc.appt(p, "completed", at(2026, 4, 3), botox)
    sc.txn(p, 30000, appt=a_first, service=botox)
    sc.txn(p, 50000, service=botox, when=at(2026, 4, 3, 15))  # no appointment link: matched by local day

    # --- visits, services, providers, time --------------------------------------------------
    p = sc.patient("midnight_edge")
    sc.appt(p, "completed", at(2026, 5, 10, 3, 30), botox)  # 23:30 on 9 May in New York
    sc.appt(p, "completed", at(2026, 5, 10, 4, 30), botox)  # 00:30 on 10 May

    p = sc.patient("two_services_one_day")
    sc.appt(p, "completed", at(2026, 3, 2), botox)
    sc.appt(p, "completed", at(2026, 3, 16, 14), botox)
    sc.appt(p, "completed", at(2026, 3, 16, 15), facial)

    p = sc.patient("dst_visits")
    sc.appt(p, "completed", at(2026, 3, 7), botox)  # EST
    sc.appt(p, "completed", at(2026, 3, 9), botox)  # EDT

    p = sc.patient("no_service")
    sc.appt(p, "completed", at(2026, 4, 1))

    p = sc.patient("usual_tie")
    sc.appt(p, "completed", at(2026, 1, 10), botox)
    sc.appt(p, "completed", at(2026, 2, 10), facial)

    p = sc.patient("prov_active")
    sc.appt(p, "completed", at(2026, 3, 1), botox, dr_active)
    p = sc.patient("prov_gone")
    sc.appt(p, "completed", at(2026, 3, 1), botox, dr_gone)
    p = sc.patient("prov_nostaff")
    sc.appt(p, "completed", at(2026, 3, 1), botox, dr_free)

    p = sc.patient("capped")
    for i in range(205):
        sc.appt(p, "completed", at(2025, 1, 1) + timedelta(days=i), botox)

    p = sc.patient("outlier_big")
    a = sc.appt(p, "completed", at(2026, 4, 7), botox)
    sc.txn(p, 99_000_000, appt=a, service=botox)  # far above 50 times the practice median

    p = sc.patient("outlier_not")
    a = sc.appt(p, "completed", at(2026, 4, 8), botox)
    sc.txn(p, 600_000, appt=a, service=botox)  # over $5,000 but nowhere near 50 times the median
    sc.txn(p, -99_000_000, when=at(2026, 4, 9))  # a huge refund is never counted as an outlier sale

    # --- consults ---------------------------------------------------------------------------
    p = sc.patient("consult_plan_day60")
    sc.appt(p, "completed", at(2026, 2, 10), consult, attrs={"quoted_plan_cents": 250000})
    sc.appt(p, "completed", at(2026, 4, 11), botox)

    p = sc.patient("consult_day61")
    sc.appt(p, "completed", at(2026, 2, 10), consult)
    sc.appt(p, "completed", at(2026, 4, 12), botox)

    p = sc.patient("consult_bad_quote")
    sc.appt(p, "completed", at(2026, 3, 1), consult, attrs={"quoted_plan_cents": "$2,500"})
    p = sc.patient("consult_string_quote")
    sc.appt(p, "completed", at(2026, 3, 1), consult, attrs={"quoted_plan_cents": "1500"})
    p = sc.patient("consult_float_quote")
    sc.appt(p, "completed", at(2026, 3, 1), consult, attrs={"quoted_plan_cents": 1500.5})

    p = sc.patient("consult_same_day")
    sc.appt(p, "completed", at(2026, 3, 20, 14), consult)
    sc.appt(p, "completed", at(2026, 3, 20, 15), botox)

    p = sc.patient("consult_only")
    sc.appt(p, "completed", at(2026, 3, 15), consult)

    # --- memberships ------------------------------------------------------------------------
    if with_memberships:
        sc.membership(sc.patient("m_active"), "active", fee=9900, prepaid=5000)
        sc.membership(sc.patient("m_cancelled"), "cancelled", ends=date(2026, 1, 31), fee=12000)
        sc.membership(sc.patient("m_lapsed"), "lapsed", ends=date(2026, 2, 28), fee=8000)
        sc.membership(sc.patient("m_expired"), "expired", ends=date(2026, 3, 31))
        sc.membership(sc.patient("m_paused"), "paused", fee=7000)
        p = sc.patient("m_multi")
        sc.membership(p, "expired", ends=date(2025, 12, 31), fee=5000)
        sc.membership(p, "cancelled", ends=None, fee=6000)
        p = sc.patient("m_balance")
        sc.membership(p, "active", prepaid=3000)
        sc.membership(p, "cancelled", prepaid=-1000)
        sc.membership(p, "expired", prepaid=None)

    # --- exclusion inputs -------------------------------------------------------------------
    sc.patient("minor", date_of_birth=date(2012, 3, 4))
    sc.patient("future_dob", date_of_birth=date(2027, 1, 1))
    sc.patient("no_dob")
    sc.patient("turns_18_today", date_of_birth=date(2008, 6, 1))
    sc.patient("day_before_18", date_of_birth=date(2008, 6, 2))
    sc.patient("dnc_true", attributes={"do_not_contact": True})
    sc.patient("dnc_yes", attributes={"do_not_contact": "Yes"})
    sc.patient("deceased_one", attributes={"deceased": 1})
    sc.patient("dnc_unparsable", attributes={"do_not_contact": "maybe"})
    sc.patient("dnc_false", attributes={"do_not_contact": "no"})
    sc.patient("dnc_blank", attributes={"do_not_contact": "  "})
    sc.patient("dnc_null", attributes={"do_not_contact": None})
    sc.patient("referral_only", attributes={"Referral Source": "Google"})

    # --- reachability inputs ----------------------------------------------------------------
    p = sc.patient("sms_granted")
    sc.consent(p, "sms", True)
    p = sc.patient("sms_revoked")
    sc.consent(p, "sms", True, NOW - timedelta(days=50))
    sc.consent(p, "sms", False, NOW - timedelta(days=10))
    p = sc.patient("sms_regranted")
    sc.consent(p, "sms", False, NOW - timedelta(days=50))
    sc.consent(p, "sms", True, NOW - timedelta(days=10))
    sc.patient("no_consent")
    sc.patient("email_only", phone=None)
    sc.patient("no_address", phone=None, email=None)

    await sc.save()
    return Messy(tenant=tenant, ids=sc.ids)


# --- random tenant for the differential test --------------------------------------------------

_STATUSES = ["completed"] * 70 + ["booked"] * 8 + ["cancelled"] * 8 + ["no_show"] * 6 + ["weird"]
_KINDS = ["service"] * 6 + ["product"] * 2 + ["membership", "package", "other"]
_MEMBERSHIP_STATUSES = ["active", "cancelled", "lapsed", "expired", "paused", "Active "]
_FLAG_VALUES = [None, True, False, "yes", "no", "Y", "1", "0", "maybe", "  ", 2, ""]


async def build_random_tenant(rng: random.Random, n: int = 500, *, now: datetime = NOW) -> uuid.UUID:
    tenant = await create_test_tenant(settings={"sms_requires_explicit_opt_in": rng.random() < 0.8})
    sc = Scene(tenant)
    services = [
        sc.service("Botox", "Injectables"),
        sc.service("Filler", "Injectables"),
        sc.service("Facial", " facials"),
        sc.service("Peel", None),
        sc.service("Consult A", "Consult"),
        sc.service("Consult B", " CONSULT "),
    ]
    providers = [
        sc.provider("P1", staff_active=True),
        sc.provider("P2", staff_active=False),
        sc.provider("P3", staff_active=None),
    ]
    for i in range(n):
        attrs: dict[str, Any] = {}
        for key in ("do_not_contact", "deceased"):
            if rng.random() < 0.06:
                attrs[key] = rng.choice(_FLAG_VALUES)
        dob_roll = rng.random()
        dob = None
        if dob_roll < 0.1:
            dob = (now - timedelta(days=rng.randint(1, 18 * 365 + 60))).date()  # minors and boundary
        elif dob_roll < 0.13:
            dob = (now + timedelta(days=rng.randint(1, 400))).date()  # invalid
        elif dob_roll < 0.9:
            dob = (now - timedelta(days=rng.randint(18 * 365, 80 * 365))).date()
        p = sc.patient(
            f"r{i}",
            date_of_birth=dob,
            attributes=attrs,
            phone=None if rng.random() < 0.15 else f"+1555{i:07d}",
            email=None if rng.random() < 0.2 else f"r{i}@example.test",
        )
        for kind in ("sms", "email"):
            for _ in range(rng.choice([0, 0, 1, 1, 2])):
                sc.consent(
                    p, kind, rng.random() < 0.6, now - timedelta(days=rng.randint(1, 900), minutes=rng.randint(0, 5))
                )
        made: list[Appointment] = []
        for _ in range(rng.choice([0, 1, 2, 3, 4, 6, 9, 14])):
            starts = now + timedelta(
                days=rng.randint(-900, 40), hours=rng.randint(-10, 10), minutes=rng.choice([0, 30])
            )
            service = rng.choice(services + [None])
            a = sc.appt(
                p,
                rng.choice(_STATUSES),
                starts,
                service,
                rng.choice(providers + [None]),
                attrs={"quoted_plan_cents": rng.choice([None, "2500", 9000, "x", 12.5, -4])}
                if service and "Consult" in service.name.upper().title() and rng.random() < 0.7
                else None,
            )
            made.append(a)
            if rng.random() < 0.04:  # exact duplicate
                made.append(sc.appt(p, a.status, a.starts_at, service, None))
            if rng.random() < 0.04:  # a second appointment the same day
                made.append(sc.appt(p, a.status, a.starts_at + timedelta(hours=1), rng.choice(services)))
        for a in made:
            if a.status == "completed" and rng.random() < 0.85:
                amount = rng.randint(500, 90000) * (-1 if rng.random() < 0.07 else 1)
                if rng.random() < 0.01:
                    amount = rng.randint(2_000_000, 9_000_000)
                svc = next((s for s in services if s.id == a.service_id), None)
                sc.txn(
                    p,
                    amount,
                    kind=rng.choice(_KINDS),
                    appt=a if rng.random() < 0.8 else None,
                    service=svc if rng.random() < 0.9 else None,
                    when=a.starts_at + timedelta(minutes=5),
                )
        for _ in range(rng.choice([0, 0, 0, 1, 2])):
            sc.txn(
                p, rng.randint(-30000, 150000), kind=rng.choice(_KINDS), when=now - timedelta(days=rng.randint(0, 600))
            )
        if rng.random() < 0.2:
            for _ in range(rng.choice([1, 1, 2, 3])):
                end = None if rng.random() < 0.4 else (now - timedelta(days=rng.randint(-60, 500))).date()
                sc.membership(
                    p,
                    rng.choice(_MEMBERSHIP_STATUSES),
                    ends=end,
                    fee=rng.choice([None, 0, 5000, 9900]),
                    prepaid=rng.choice([None, -500, 0, 2500, 10000]),
                    updated=now - timedelta(days=rng.randint(0, 800)),
                )
    await sc.save()
    return tenant
