"""A fixed 300-patient fixture for the golden test. Built from index arithmetic only (no randomness), so
the same facts come out on every Python version and the checked-in snapshot stays valid."""

import uuid
from datetime import UTC, date, datetime, timedelta

from builders import blank
from factories import NOW, TZ

from clinic_reactivation.analysis.exclusions import FlagValue
from clinic_reactivation.analysis.facts import PatientFacts, ReachabilityIngredients
from clinic_reactivation.analysis.revenue import MeasuredRate
from clinic_reactivation.analysis.scoring import PastResponse

TODAY = date(2026, 6, 1)  # NOW is 11:00 on this day in New York
N = 300
SERVICES = [uuid.UUID(int=0x1000 + i) for i in range(3)]
SERVICE_NAMES = {SERVICES[0]: "Botox", SERVICES[1]: "Facial", SERVICES[2]: "Consult"}
CATEGORIES = ["injectables", "facials", "consult"]
PROVIDERS = [uuid.UUID(int=0x2000 + i) for i in range(2)]


def pid(i: int) -> uuid.UUID:
    return uuid.UUID(int=i + 1)


def _patient(i: int) -> PatientFacts:
    visits = 1 + i % 6
    days = (i * 7) % 380
    last = TODAY - timedelta(days=days)
    spend = 5000 + (i * 977) % 90000
    consult = i % 19 == 7
    has_provider = i % 7 != 0
    days_list = tuple(last - timedelta(days=35 * k) for k in reversed(range(visits)))
    fields = dict(
        patient_id=pid(i),
        visit_count=visits,
        first_visit_day=days_list[0],
        last_visit_day=last,
        visit_days=days_list,
        visit_starts=tuple(datetime(d.year, d.month, d.day, 15, tzinfo=UTC) for d in days_list),
        spend_cents=spend,
        ticket_total_cents=spend,
        average_ticket_cents=(2 * spend + visits) // (2 * visits),
        usual_service_id=SERVICES[i % 3],
        usual_service_category_norm=CATEGORIES[i % 3],
        usual_service_visit_days=max(1, min(visits, 1 + i % 3)),
        usual_service_ticket_total_cents=spend // 2 if i % 4 else None,
        first_visit_ticket_cents=4000 + (i * 131) % 20000 if i % 5 else None,
        first_treatment_ticket_cents=6000 + (i * 211) % 30000 if i % 3 else None,
        usual_provider_id=PROVIDERS[i % 2] if has_provider else None,
        provider_staff_active=[True, False, None][i % 3] if has_provider else None,
        has_future_booking=i % 11 == 4,
        prepaid_balance_cents=4000 + (i % 5) * 1000 if i % 13 == 5 else 0,
        ingredients=ReachabilityIngredients([True, False, None][i % 3], None, i % 9 != 0, True, True),
        past_appointments=visits,
    )
    if i % 17 == 6:
        fields.update(
            membership_rows=1,
            latest_membership_status="cancelled" if i % 34 == 6 else "expired",
            latest_membership_end=date(2026, 1, 15) - timedelta(days=i % 40),
            latest_membership_fee_cents=9900,
        )
    if i % 23 == 9:
        fields.update(membership_rows=1, latest_membership_status="paused", unknown_membership_status={"paused": 1})
    if consult:
        fields.update(
            latest_consult_day=TODAY - timedelta(days=30 + (i * 3) % 100),
            latest_consult_service_id=SERVICES[2],
            converted_within_window=i % 2 == 0,
            quoted_plan_cents=120000 if i % 3 == 0 else None,
        )
    if i % 29 == 0:
        fields["duplicate_appointments"] = 1
    if i % 43 == 0:
        fields["completed_in_future"] = 1
    if i % 31 == 0:
        fields.update(stale_booked_in_past=1, past_appointments=visits + 1)
    if i % 97 == 0:
        fields["outlier_transactions"] = 1
    if i % 47 == 0:
        fields["unknown_appointment_status"] = {"weird": 1}
    if i % 89 == 0:
        fields["negative_spend"] = True
    if i % 50 == 0:
        fields.update(do_not_contact=FlagValue.TRUE, do_not_contact_raw=True)
    if i % 53 == 1:
        fields["is_minor"] = True
    if i % 41 == 2:
        fields.update(deceased=FlagValue.TRUE, deceased_raw=1)
    if i % 61 == 3:
        fields.update(do_not_contact=FlagValue.UNPARSABLE, do_not_contact_raw="maybe")
    if i % 37 == 3:  # no completed visit at all
        fields.update(
            visit_count=0, first_visit_day=None, last_visit_day=None, visit_days=(), visit_starts=(), spend_cents=0,
            ticket_total_cents=0, average_ticket_cents=None, usual_service_id=None, usual_service_category_norm=None,
            usual_service_visit_days=0, usual_service_ticket_total_cents=None, first_visit_ticket_cents=None,
            first_treatment_ticket_cents=None, usual_provider_id=None, provider_staff_active=None, past_appointments=0,
        )  # fmt: skip
    return blank(**fields)


def golden_facts() -> list[PatientFacts]:
    return [_patient(i) for i in range(N)]


def golden_inputs():
    """Everything analyse() needs besides settings, in a fixed shape."""
    measured = {"one_and_done": MeasuredRate(booked=9, contacted=30)}
    responders = {
        pid(i): PastResponse.BOOKED if i % 7 == 0 else PastResponse.NOT_BOOKED
        for i in range(N)
        if i % 5 == 0 or i % 7 == 0
    }
    previous = frozenset(pid(i) for i in range(N) if i % 4 == 0)
    return measured, responders, previous, NOW, TZ
