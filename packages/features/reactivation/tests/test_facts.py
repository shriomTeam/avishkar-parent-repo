import random
from dataclasses import fields
from datetime import date, datetime, timedelta
from fractions import Fraction

import pytest
from builders import blank
from factories import NOW, TZ, Scene, at, build_messy_tenant, build_random_tenant
from reference_facts import read_rows, reference_facts

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.core import Tenant
from clinic_engagement.compliance import can_contact
from clinic_reactivation.analysis.exclusions import (
    FlagValue,
    assign_spend_percentiles,
    exclusion_reason,
    parse_flag,
)
from clinic_reactivation.analysis.facts import (
    BadTimezone,
    PatientFacts,
    ReachabilityIngredients,
    load_facts,
    reachable_from,
)


async def load(tenant, now=NOW, tz=TZ, **kw) -> list[PatientFacts]:
    async with tenant_session(tenant) as s:
        return await load_facts(s, now, tz, **kw)


def as_dict(f: PatientFacts) -> dict:
    d = {x.name: getattr(f, x.name) for x in fields(f) if x.name != "ingredients"}
    d.update(
        consent_sms=f.ingredients.consent_sms,
        consent_email=f.ingredients.consent_email,
        has_phone=f.ingredients.has_phone,
        has_email=f.ingredients.has_email,
        sms_requires_explicit_opt_in=f.ingredients.sms_requires_explicit_opt_in,
        do_not_contact=f.do_not_contact.value,
        deceased=f.deceased.value,
    )
    return d


async def assert_matches_reference(tenant, *, cohort_min=20) -> int:
    async with tenant_session(tenant) as s:
        facts = await load_facts(s, NOW, TZ, cohort_min=cohort_min)
        rows = await read_rows(s)
    expected = reference_facts(rows, NOW, TZ, cohort_min=cohort_min)
    assert {f.patient_id for f in facts} == set(expected)
    for f in facts:
        got, want = as_dict(f), expected[f.patient_id]
        for key in want:
            assert got[key] == want[key], f"{key} differs for patient {f.patient_id}: {got[key]!r} != {want[key]!r}"
    return len(facts)


@pytest.fixture(scope="module")
async def messy():
    m = await build_messy_tenant()
    facts = await load(m.tenant)
    by_id = {f.patient_id: f for f in facts}
    names = {k: v for k, v in m.ids.items() if not k.startswith(("service:", "provider:"))}
    return m, {name: by_id[pid] for name, pid in names.items()}, facts


def expect(f: PatientFacts, **want):
    for key, value in want.items():
        assert getattr(f, key) == value, f"{key}: {getattr(f, key)!r} != {value!r}"


# --- every field on the messy tenant ---------------------------------------------------------


async def test_every_patient_is_returned_in_id_order(messy):
    m, F, facts = messy
    assert len(facts) == len(F)
    assert [f.patient_id for f in facts] == sorted(f.patient_id for f in facts)


async def test_ordinary_patient(messy):
    m, F, _ = messy
    botox = m.ids["service:Botox"]
    expect(
        F["regular"],
        visit_count=3,
        visit_days=(date(2025, 12, 4), date(2026, 2, 3), date(2026, 4, 2)),
        visit_starts=(at(2025, 12, 4), at(2026, 2, 3), at(2026, 4, 2)),
        first_visit_day=date(2025, 12, 4),
        last_visit_day=date(2026, 4, 2),
        usual_service_id=botox,
        usual_service_category_norm="injectables",
        usual_service_visit_days=3,
        usual_provider_id=m.ids["provider:Dr Active"],
        provider_staff_active=True,
        spend_cents=120000,
        ticket_total_cents=120000,
        average_ticket_cents=40000,
        usual_service_ticket_total_cents=120000,
        first_visit_ticket_cents=40000,
        first_treatment_ticket_cents=40000,
        has_future_booking=False,
        latest_consult_day=None,
        converted_within_window=None,
        membership_rows=0,
        duplicate_appointments=0,
        completed_in_future=0,
        stale_booked_in_past=0,
        past_appointments=3,
        negative_spend=False,
        negative_ticket=False,
    )
    assert F["regular"].unknown_appointment_status == {}
    assert F["regular"].reachability.sms and F["regular"].reachability.email


async def test_duplicate_appointments_count_once(messy):
    _, F, _ = messy
    expect(
        F["duplicate_appts"],
        duplicate_appointments=2,
        visit_count=1,
        ticket_total_cents=30000,
        usual_service_visit_days=1,
        past_appointments=1,
    )


async def test_completed_in_the_future_is_not_a_visit(messy):
    _, F, _ = messy
    expect(
        F["future_completed"],
        completed_in_future=1,
        visit_count=1,
        last_visit_day=date(2026, 2, 20),
        has_future_booking=False,
        past_appointments=1,
    )


async def test_stale_booked_is_neither_a_booking_nor_a_visit(messy):
    _, F, _ = messy
    expect(
        F["stale_booked"],
        stale_booked_in_past=1,
        has_future_booking=False,
        visit_count=1,
        past_appointments=2,
        last_visit_day=date(2026, 1, 15),
    )


async def test_future_booking_and_the_boundary_at_now(messy):
    _, F, _ = messy
    expect(F["future_booking"], has_future_booking=True, stale_booked_in_past=0)
    expect(F["booking_at_now"], has_future_booking=True, stale_booked_in_past=0, past_appointments=1)


async def test_unknown_status_values_are_counted_not_guessed(messy):
    _, F, _ = messy
    expect(F["unknown_status"], unknown_appointment_status={"rescheduled": 2, "weird": 1}, visit_count=1)


async def test_patients_without_visits(messy):
    _, F, _ = messy
    expect(
        F["no_completed"],
        visit_count=0,
        first_visit_day=None,
        last_visit_day=None,
        visit_days=(),
        average_ticket_cents=None,
        usual_service_id=None,
        past_appointments=2,
        spend_cents=0,
    )
    expect(F["empty"], visit_count=0, past_appointments=0, spend_cents=0, ticket_total_cents=0)


async def test_refund_larger_than_sales_clamps_spend_to_zero(messy):
    _, F, _ = messy
    expect(
        F["refund_big"],
        spend_cents=0,
        negative_spend=True,
        ticket_total_cents=0,
        negative_ticket=True,
        average_ticket_cents=0,
        usual_service_ticket_total_cents=None,
    )


async def test_negative_service_refund_reduces_ticket(messy):
    _, F, _ = messy
    expect(
        F["refund_netting"],
        spend_cents=40000,
        ticket_total_cents=40000,
        average_ticket_cents=20000,
        usual_service_ticket_total_cents=30000,
        first_visit_ticket_cents=60000,
        first_treatment_ticket_cents=60000,
        negative_spend=False,
        negative_ticket=False,
    )


async def test_negative_membership_amount_reduces_spend_only(messy):
    _, F, _ = messy
    expect(
        F["membership_neg"],
        spend_cents=35000,
        ticket_total_cents=30000,
        average_ticket_cents=30000,
        negative_spend=False,
        negative_ticket=False,
    )


async def test_package_purchase_counts_as_spend_not_ticket(messy):
    _, F, _ = messy
    expect(F["package_buyer"], spend_cents=170000, ticket_total_cents=20000, average_ticket_cents=20000)


async def test_transactions_without_an_appointment_link_match_by_local_day(messy):
    _, F, _ = messy
    expect(
        F["tx_by_day"],
        ticket_total_cents=80000,
        average_ticket_cents=40000,
        first_visit_ticket_cents=30000,
        first_treatment_ticket_cents=30000,
        usual_service_ticket_total_cents=80000,
    )


async def test_outlier_transactions_are_counted_never_capped(messy):
    _, F, _ = messy
    expect(F["outlier_big"], outlier_transactions=1, spend_cents=99_000_000, ticket_total_cents=99_000_000)
    expect(F["outlier_not"], outlier_transactions=0)  # 600000 is under 50 times the median; the refund is negative
    assert F["regular"].outlier_transactions == 0


async def test_outlier_boundaries_are_strict():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    p = sc.patient("anchor")
    for i in range(11):  # eleven 20000 amounts pin the median at 20000, so 50 times is exactly 1,000,000
        sc.appt(p, "completed", at(2026, 1, 1) + timedelta(days=i))
        sc.txn(p, 20000, when=at(2026, 1, 1) + timedelta(days=i))
    at_limit, over_limit = sc.patient("at_limit"), sc.patient("over_limit")
    sc.appt(at_limit, "completed", at(2026, 3, 1))
    sc.txn(at_limit, 1_000_000, when=at(2026, 3, 1))
    sc.appt(over_limit, "completed", at(2026, 3, 1))
    sc.txn(over_limit, 1_000_001, when=at(2026, 3, 1))
    await sc.save()
    got = {f.patient_id: f for f in await load(tenant)}
    assert got[at_limit.id].outlier_transactions == 0  # exactly 50 times the median is not above it
    assert got[over_limit.id].outlier_transactions == 1
    assert got[over_limit.id].spend_cents == 1_000_001  # the amount is kept in full

    low = await create_test_tenant()
    sc = Scene(low)
    p = sc.patient("anchor")
    for i in range(11):  # a median of 5000 puts 50 times at 250,000, so the $5,000 floor (500,000) decides
        sc.appt(p, "completed", at(2026, 1, 1) + timedelta(days=i))
        sc.txn(p, 5000, when=at(2026, 1, 1) + timedelta(days=i))
    floor, above = sc.patient("floor"), sc.patient("above")
    sc.appt(floor, "completed", at(2026, 3, 1))
    sc.txn(floor, 500_000, when=at(2026, 3, 1))
    sc.appt(above, "completed", at(2026, 3, 1))
    sc.txn(above, 500_001, when=at(2026, 3, 1))
    await sc.save()
    got = {f.patient_id: f for f in await load(low)}
    assert got[floor.id].outlier_transactions == 0 and got[above.id].outlier_transactions == 1


async def test_no_positive_transactions_means_no_outliers():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    p = sc.patient("refunds_only")
    sc.appt(p, "completed", at(2026, 3, 1))
    sc.txn(p, -900_000_000, when=at(2026, 3, 1))
    await sc.save()
    assert [f.outlier_transactions for f in await load(tenant)] == [0]


async def test_visits_are_distinct_clinic_local_days(messy):
    m, F, _ = messy
    expect(F["midnight_edge"], visit_count=2, visit_days=(date(2026, 5, 9), date(2026, 5, 10)))
    expect(
        F["two_services_one_day"],
        visit_count=2,
        usual_service_id=m.ids["service:Botox"],
        usual_service_visit_days=2,
        visit_starts=(at(2026, 3, 2), at(2026, 3, 16, 14)),
    )
    expect(
        F["dst_visits"], visit_days=(date(2026, 3, 7), date(2026, 3, 9)), visit_starts=(at(2026, 3, 7), at(2026, 3, 9))
    )


async def test_usual_service_rules(messy):
    m, F, _ = messy
    expect(
        F["no_service"],
        visit_days_without_service=1,
        usual_service_id=None,
        usual_service_category_norm=None,
        visit_count=1,
    )
    expect(F["usual_tie"], usual_service_id=m.ids["service:Facial"], usual_service_category_norm="facials")


async def test_provider_continuity_inputs(messy):
    m, F, _ = messy
    expect(F["prov_active"], provider_staff_active=True, usual_provider_id=m.ids["provider:Dr Active"])
    expect(F["prov_gone"], provider_staff_active=False)
    expect(F["prov_nostaff"], provider_staff_active=None, usual_provider_id=m.ids["provider:Dr Free"])


async def test_visit_lists_are_capped_but_counts_are_true(messy):
    _, F, _ = messy
    f = F["capped"]
    assert f.visit_count == 205 and len(f.visit_days) == 200 and len(f.visit_starts) == 200
    assert f.first_visit_day == date(2025, 1, 1)
    assert f.visit_days[0] == date(2025, 1, 1) + timedelta(days=5)
    assert f.visit_days[-1] == f.last_visit_day == date(2025, 1, 1) + timedelta(days=204)
    assert list(f.visit_days) == sorted(f.visit_days)


async def test_consults(messy):
    m, F, _ = messy
    consult = m.ids["service:Consult"]
    expect(
        F["consult_plan_day60"],
        latest_consult_day=date(2026, 2, 10),
        latest_consult_service_id=consult,
        quoted_plan_cents=250000,
        quoted_plan_invalid=False,
        converted_within_window=True,
        consult_visit_days=1,
    )
    expect(F["consult_day61"], converted_within_window=False, quoted_plan_cents=None, quoted_plan_invalid=False)
    expect(F["consult_bad_quote"], quoted_plan_cents=None, quoted_plan_invalid=True, converted_within_window=False)
    expect(F["consult_string_quote"], quoted_plan_cents=1500, quoted_plan_invalid=False)
    expect(F["consult_float_quote"], quoted_plan_cents=None, quoted_plan_invalid=True)
    expect(F["consult_same_day"], converted_within_window=True, consult_visit_days=0)
    expect(
        F["consult_only"],
        converted_within_window=False,
        consult_visit_days=1,
        visit_count=1,
        first_treatment_ticket_cents=None,
    )


async def test_memberships_in_every_status(messy):
    _, F, _ = messy
    expect(
        F["m_active"],
        membership_rows=1,
        has_active_membership=True,
        latest_membership_status="active",
        latest_membership_end=None,
        latest_membership_fee_cents=9900,
        prepaid_balance_cents=5000,
    )
    expect(
        F["m_cancelled"],
        has_active_membership=False,
        latest_membership_status="cancelled",
        latest_membership_end=date(2026, 1, 31),
        latest_membership_fee_cents=12000,
        prepaid_balance_cents=0,
    )
    expect(F["m_lapsed"], latest_membership_status="lapsed", latest_membership_end=date(2026, 2, 28))
    expect(F["m_expired"], latest_membership_status="expired", latest_membership_fee_cents=None)
    expect(F["m_paused"], latest_membership_status="paused", unknown_membership_status={"paused": 1})
    expect(
        F["m_multi"],
        membership_rows=2,
        latest_membership_status="cancelled",
        latest_membership_end=None,
        latest_membership_fee_cents=6000,
        has_active_membership=False,
    )
    expect(F["m_balance"], membership_rows=3, prepaid_balance_cents=3000, has_active_membership=True)
    assert F["regular"].unknown_membership_status == {}


async def test_date_of_birth_inputs(messy):
    _, F, _ = messy
    expect(F["minor"], is_minor=True, invalid_dob=False)
    expect(F["future_dob"], is_minor=False, invalid_dob=True)
    expect(F["no_dob"], is_minor=False, invalid_dob=False)
    expect(F["turns_18_today"], is_minor=False)
    expect(F["day_before_18"], is_minor=True)


async def test_exclusion_flags(messy):
    _, F, _ = messy
    expect(F["dnc_true"], do_not_contact=FlagValue.TRUE, do_not_contact_raw=True)
    expect(F["dnc_yes"], do_not_contact=FlagValue.TRUE)
    expect(F["deceased_one"], deceased=FlagValue.TRUE, deceased_raw=1)
    expect(F["dnc_unparsable"], do_not_contact=FlagValue.UNPARSABLE)
    expect(F["dnc_false"], do_not_contact=FlagValue.FALSE)
    expect(F["dnc_blank"], do_not_contact=FlagValue.ABSENT)
    expect(F["dnc_null"], do_not_contact=FlagValue.ABSENT)
    expect(F["referral_only"], do_not_contact=FlagValue.ABSENT, deceased=FlagValue.ABSENT)
    assert exclusion_reason(F["dnc_true"]) == "do_not_contact"
    assert exclusion_reason(F["deceased_one"]) == "deceased"
    assert exclusion_reason(F["dnc_unparsable"]) == "unparsable_exclusion_flag"
    assert exclusion_reason(F["minor"]) == "minor"
    assert exclusion_reason(F["dnc_false"]) is None
    assert exclusion_reason(F["future_dob"]) is None  # an invalid DOB does not exclude


async def test_reachability_inputs(messy):
    _, F, _ = messy
    assert F["sms_granted"].reachability.sms
    assert F["sms_revoked"].ingredients.consent_sms is False and not F["sms_revoked"].reachability.sms
    assert F["sms_revoked"].reachability.email and F["sms_revoked"].reachability.either
    assert F["sms_regranted"].ingredients.consent_sms is True and F["sms_regranted"].reachability.sms
    assert not F["no_consent"].reachability.sms and F["no_consent"].reachability.email
    assert not F["email_only"].ingredients.has_phone and F["email_only"].reachability.either
    assert not F["no_address"].reachability.either
    assert F["regular"].ingredients.sms_requires_explicit_opt_in is True


async def test_no_memberships_variant_is_all_zero():
    m = await build_messy_tenant(with_memberships=False)
    facts = await load(m.tenant)
    assert facts and all(f.membership_rows == 0 and not f.has_active_membership for f in facts)
    assert all(f.prepaid_balance_cents == 0 and f.latest_membership_status is None for f in facts)


# --- the reference ---------------------------------------------------------------------------


async def test_messy_tenant_matches_the_reference():
    m = await build_messy_tenant()
    patients = [k for k in m.ids if not k.startswith(("service:", "provider:"))]
    assert await assert_matches_reference(m.tenant) == len(patients)


async def test_500_random_patients_match_the_reference():
    tenant = await build_random_tenant(random.Random(42), 500)
    assert await assert_matches_reference(tenant) == 500


async def test_facts_are_deterministic():
    tenant = await build_random_tenant(random.Random(7), 120)
    assert await load(tenant) == await load(tenant)


# --- reachable_from pinned to the engine -----------------------------------------------------

_CONSENT_STATES = {
    "none": [],
    "granted": [True],
    "revoked": [False],
    "granted_then_revoked": [True, False],
    "revoked_then_granted": [False, True],
}


@pytest.mark.parametrize("requires_opt_in", [True, False])
async def test_reachable_from_agrees_with_can_contact(requires_opt_in):
    tenant = await create_test_tenant(settings={"sms_requires_explicit_opt_in": requires_opt_in})
    sc = Scene(tenant)
    cases: dict[str, tuple] = {}
    for sms_state, sms_rows in _CONSENT_STATES.items():
        for email_state, email_rows in _CONSENT_STATES.items():
            for phone in (True, False):
                for email in (True, False):
                    name = f"{sms_state}|{email_state}|{phone}|{email}"
                    p = sc.patient(name, phone="+15550009999" if phone else None, email="a@x.test" if email else None)
                    for kind, rows in (("sms", sms_rows), ("email", email_rows)):
                        for i, granted in enumerate(rows):
                            sc.consent(p, kind, granted, NOW - timedelta(days=100 - 10 * i))
                    cases[name] = (p.id, phone, email)
    await sc.save()

    async with tenant_session(tenant) as s:
        facts = {f.patient_id: f for f in await load_facts(s, NOW, TZ)}
        tenant_row = await s.get(Tenant, tenant)
        for name, (pid, has_phone, has_email) in cases.items():
            sms_ok, _ = await can_contact(s, tenant_row, pid, "sms")
            email_ok, _ = await can_contact(s, tenant_row, pid, "email")
            got = reachable_from(facts[pid].ingredients)
            assert got.sms == (sms_ok and has_phone), name
            assert got.email == (email_ok and has_email), name
            assert got.either == (got.sms or got.email)
            assert facts[pid].ingredients.sms_requires_explicit_opt_in is requires_opt_in


def test_reachable_from_is_a_pure_function_of_its_inputs():
    base = dict(consent_sms=None, consent_email=None, has_phone=True, has_email=True)
    assert not reachable_from(ReachabilityIngredients(**base, sms_requires_explicit_opt_in=True)).sms
    assert reachable_from(ReachabilityIngredients(**base, sms_requires_explicit_opt_in=False)).sms


# --- misc ------------------------------------------------------------------------------------


async def test_bad_timezone_and_naive_now_are_rejected_before_any_query():
    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        with pytest.raises(BadTimezone):
            await load_facts(s, NOW, "Mars/Olympus")
        with pytest.raises(ValueError, match="timezone-aware"):
            await load_facts(s, datetime(2026, 6, 1, 15), TZ)


async def test_an_empty_tenant_gives_no_facts():
    assert await load(await create_test_tenant()) == []


def test_parse_flag():
    cases = [
        (True, FlagValue.TRUE),
        (False, FlagValue.FALSE),
        ("TRUE", FlagValue.TRUE),
        (" yes ", FlagValue.TRUE),
        ("y", FlagValue.TRUE),
        ("1", FlagValue.TRUE),
        (1, FlagValue.TRUE),
        ("no", FlagValue.FALSE),
        ("N", FlagValue.FALSE),
        ("0", FlagValue.FALSE),
        (0, FlagValue.FALSE),
        (None, FlagValue.ABSENT),
        ("", FlagValue.ABSENT),
        ("   ", FlagValue.ABSENT),
        ("maybe", FlagValue.UNPARSABLE),
        (2, FlagValue.UNPARSABLE),
        (1.5, FlagValue.UNPARSABLE),
        (["yes"], FlagValue.UNPARSABLE),
        ({"a": 1}, FlagValue.UNPARSABLE),
    ]
    for raw, want in cases:
        assert parse_flag(raw) is want, raw


# --- percentile (pure) -----------------------------------------------------------------------


def test_percentile_boundary_079_and_080():
    cohort = [blank(spend_cents=i * 100) for i in range(101)]
    out = assign_spend_percentiles(cohort)
    assert out[79].spend_percentile == Fraction(79, 100) and out[79].spend_percentile < Fraction(8, 10)
    assert out[80].spend_percentile == Fraction(80, 100) and out[80].spend_percentile >= Fraction(8, 10)
    assert out[0].spend_percentile == 0 and out[100].spend_percentile == 1


def test_percentile_needs_a_cohort_of_twenty():
    assert all(f.spend_percentile is None for f in assign_spend_percentiles([blank(spend_cents=i) for i in range(19)]))
    twenty = assign_spend_percentiles([blank(spend_cents=i) for i in range(20)])
    assert all(f.spend_percentile is not None for f in twenty)
    smaller = [blank(spend_cents=i) for i in range(19)] + [blank(spend_cents=99, deceased=FlagValue.TRUE)]
    assert all(f.spend_percentile is None for f in assign_spend_percentiles(smaller))  # exclusion shrinks it


def test_percentile_ties_share_a_value_and_non_scored_get_none():
    cohort = [blank(spend_cents=100) for _ in range(10)] + [blank(spend_cents=50 * i) for i in range(1, 12)]
    visitless = blank(visit_count=0, spend_cents=0)
    minor = blank(is_minor=True, spend_cents=500)
    out = assign_spend_percentiles([*cohort, visitless, minor])
    tied = {f.spend_percentile for f in out[:10]}
    assert len(tied) == 1 and tied != {None}
    assert out[-2].spend_percentile is None and out[-1].spend_percentile is None
