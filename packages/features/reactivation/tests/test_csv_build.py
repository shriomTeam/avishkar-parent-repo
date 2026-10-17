"""Lines -> facts: the rules that are easy to get wrong, each stated as a small file."""

import csv
import io
import random
from datetime import date

from clinic_reactivation.analysis.exclusions import FlagValue
from clinic_reactivation.analysis.facts import Reachability, reachable_from
from clinic_reactivation.csv_import.build import Built, build_facts, derive_id
from clinic_reactivation.csv_import.parser import parse_csv

TODAY = date(2026, 10, 18)


def build(rows: list[dict[str, str]], **kw) -> Built:
    header = list(dict.fromkeys(k for r in rows for k in r))
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([r.get(h, "") for h in header])
    return build_facts(parse_csv(out.getvalue().encode(), today=TODAY), today=TODAY, **kw)


def line(day="2026-03-01", kind="service", amount="100.00", name="Botox", **kw) -> dict[str, str]:
    base = {"patient_id": "P1", "visit_date": day, "line_kind": kind, "amount": amount, "service_name": name}
    return {**base, **kw}


def one(rows, **kw):
    (facts,) = build(rows, **kw).facts
    return facts


def test_ids_are_derived_from_the_text_and_stable():
    a, b = one([line()]), one([line(patient_id=" P1 ")])
    assert a.patient_id == b.patient_id == derive_id("patient", "P1")
    assert derive_id("patient", "p1") != derive_id("patient", "P1")
    assert derive_id("service", "botox") == one([line()]).usual_service_id


def test_only_service_or_product_lines_of_zero_or_more_make_a_visit():
    f = one([
        line("2026-03-01"),                                     # a visit
        line("2026-03-02", "product", "0.00", ""),              # a free product still a visit
        line("2026-03-03", "membership", "99.00", ""),          # spend, not a visit
        line("2026-03-04", "package", "500.00", ""),
        line("2026-03-05", "other", "10.00", ""),
        line("2026-03-06", "service", "-50.00"),                # a refund
    ])  # fmt: skip
    assert f.visit_count == 2 and f.visit_days == (date(2026, 3, 1), date(2026, 3, 2))
    assert f.last_visit_day == date(2026, 3, 2) and f.spend_cents == 10000 + 0 + 9900 + 50000 + 1000 - 5000
    assert f.visit_days_without_service == 1  # the product-only day


def test_refunds_net_against_ticket_only_for_service_and_product():
    f = one(
        [
            line(amount="100.00"),
            line("2026-03-02", "product", "40.00", ""),
            line("2026-03-03", "membership", "-30.00", ""),
        ]
    )
    assert f.ticket_total_cents == 14000 and f.spend_cents == 11000
    f = one([line(amount="100.00"), line("2026-03-01", "service", "-300.00")])
    assert f.ticket_total_cents == 0 and f.negative_ticket and f.spend_cents == 0 and f.negative_spend
    assert f.average_ticket_cents == 0


def test_a_visit_day_is_one_visit_however_many_lines_or_visit_ids():
    f = one([line(visit_id="V1"), line(kind="product", amount="20.00", name="", visit_id="V1"), line(visit_id="V2")])
    assert f.visit_count == 1 and f.first_visit_ticket_cents == 22000


def test_usual_service_provider_and_category():
    rows = [
        line("2026-01-01", name="Facial", service_category="Facials", provider_name="Dr. Lee"),
        line("2026-02-01", name="Botox", service_category="Injectables", provider_name="Dr. Lee"),
        line("2026-03-01", name="botox ", service_category="injectables", provider_name="Dr. Kim"),
    ]
    f = one(rows)
    assert f.usual_service_id == derive_id("service", "botox") and f.usual_service_visit_days == 2
    assert f.usual_service_category_norm == "injectables"
    assert f.usual_provider_id == derive_id("provider", "dr. lee") and f.provider_staff_active is None
    assert f.usual_service_ticket_total_cents == 20000
    # a tie goes to the most recent day, then to the smaller id
    tie = one([line("2026-01-01", name="Facial"), line("2026-02-01", name="Botox")])
    assert tie.usual_service_id == derive_id("service", "botox")


def test_consults_by_visit_type_or_category_and_conversion_window():
    consult = line("2026-01-01", name="Consultation", visit_type="consult", amount="0.00")
    f = one([consult, line("2026-02-15")])  # 45 days later: converted
    assert f.latest_consult_day == date(2026, 1, 1) and f.converted_within_window is True
    assert f.consult_visit_days == 1 and f.first_treatment_ticket_cents == 10000
    f = one([consult, line("2026-03-15")])  # 73 days later: not converted
    assert f.converted_within_window is False
    f = one([line("2026-01-01", name="Consult", service_category="Consult"), line("2026-03-15")])
    assert f.latest_consult_day == date(2026, 1, 1)  # the category alone marks it
    assert one([line()]).converted_within_window is None and one([line()]).latest_consult_day is None


def test_memberships_balances_and_ignored_details():
    f = one([line(membership_status="Cancelled", membership_ended_on="2026-02-01", membership_monthly_fee="99.00",
                  prepaid_balance="25.50")])  # fmt: skip
    assert (f.membership_rows, f.latest_membership_status, f.latest_membership_end) == (
        1,
        "cancelled",
        date(2026, 2, 1),
    )
    assert (f.latest_membership_fee_cents, f.prepaid_balance_cents, f.has_active_membership) == (9900, 2550, False)
    none = build([line(membership_status="none", membership_ended_on="2026-02-01", membership_monthly_fee="9.00")])
    assert none.facts[0].membership_rows == 0 and none.facts[0].latest_membership_end is None
    assert none.notes == {"membership_details_ignored": 1}
    balance_only = one([line(prepaid_balance="10.00")])
    assert balance_only.membership_rows == 1 and balance_only.latest_membership_status is None
    assert one([line(prepaid_balance="0.00")]).membership_rows == 0
    assert one([line(membership_status="active")]).has_active_membership is True


def test_next_appointment_makes_a_future_booking_from_today_on():
    assert one([line(next_appointment_date="2026-10-18")]).has_future_booking is True
    assert one([line(next_appointment_date="2026-12-01")]).has_future_booking is True
    past = build([line(next_appointment_date="2026-10-17")])
    assert past.facts[0].has_future_booking is False and past.notes == {"past_next_appointment_ignored": 1}
    assert one([line()]).has_future_booking is False


def test_blank_consent_maps_into_the_existing_reachability_rule():
    contact = {"email": "a@x.test", "phone": "555-0101"}

    def reach(requires_opt_in=True, **consent) -> Reachability:
        return reachable_from(one([line(**contact, **consent)], requires_opt_in=requires_opt_in).ingredients)

    assert reach(sms_consent="yes", email_consent="yes") == Reachability(sms=True, email=True)
    assert reach(sms_consent="no", email_consent="no") == Reachability(sms=False, email=False)
    assert reach(sms_consent="", email_consent="") == Reachability(sms=False, email=True)  # unknown: SMS blocked
    assert reach(False, sms_consent="") == Reachability(sms=True, email=True)  # the clinic's opt-in rule is off
    # no consent columns at all: every consent is unknown
    f = one([line(**contact)])
    assert (f.ingredients.consent_sms, f.ingredients.consent_email) == (None, None)
    assert reachable_from(f.ingredients) == Reachability(sms=False, email=True)


def test_malformed_contacts_count_as_missing_with_a_note():
    built = build(
        [line(email="nope", phone="12"), line("2026-04-01", patient_id="P2", email="a@x.test", phone="555-0101")]
    )
    by = {f.patient_id: f.ingredients for f in built.facts}
    bad, good = by[derive_id("patient", "P1")], by[derive_id("patient", "P2")]
    assert (bad.has_email, bad.has_phone, good.has_email, good.has_phone) == (False, False, True, True)
    assert built.notes == {"email_treated_as_missing": 1, "phone_treated_as_missing": 1}


def test_exclusion_flags():
    f = one([line(do_not_contact="yes", deceased="no")])
    assert (f.do_not_contact, f.deceased) == (FlagValue.TRUE, FlagValue.FALSE)
    assert (f.do_not_contact_raw, f.deceased_raw) == (True, False)
    f = one([line()])
    assert (f.do_not_contact, f.deceased, f.do_not_contact_raw) == (FlagValue.ABSENT, FlagValue.ABSENT, None)


def test_names_and_external_ids():
    built = build([line(patient_name="  Maya   Rao "), line(patient_id="P2", name="Facial")])
    names = {built.external_ids[f.patient_id]: built.display_names[f.patient_id] for f in built.facts}
    assert names == {"P1": "Maya Rao", "P2": None}
    assert set(built.service_names.values()) == {"Botox", "Facial"}


def test_row_order_does_not_change_the_facts():
    rows = [line(f"2026-0{m}-0{d}", patient_id=f"P{p}", name=n, amount=f"{10 * m + d}.00", provider_name=f"Dr {d % 2}")
            for p in range(6) for m in range(1, 4) for d in range(1, 4) for n in ("Botox", "Facial")]  # fmt: skip
    shuffled = rows[:]
    random.Random(7).shuffle(shuffled)
    key = lambda f: f.patient_id.int  # noqa: E731
    a = sorted(build(rows).facts, key=key)
    b = sorted(build(shuffled).facts, key=key)
    assert a == b


def test_outliers_use_fifty_times_the_median_of_positive_amounts():
    rows = [line(f"2026-03-{d:02d}", patient_id=f"P{d}", amount="100.00") for d in range(1, 10)]
    rows.append(line("2026-03-10", patient_id="P10", amount="6000.00"))  # above $5,000 and 50 x $100
    rows.append(line("2026-03-11", patient_id="P11", amount="4000.00"))  # above 50 x $100 but under $5,000
    counts = {f.patient_id: f.outlier_transactions for f in build(rows).facts}
    assert counts[derive_id("patient", "P10")] == 1 and counts[derive_id("patient", "P11")] == 0
    assert sum(counts.values()) == 1
