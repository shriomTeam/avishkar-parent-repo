import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from builders import blank
from factories import NOW, Scene

from clinic_core.database import tenant_session
from clinic_core.testing import create_test_tenant
from clinic_db.models.reactivation import Campaign, CampaignTarget
from clinic_reactivation.analysis.revenue import (
    FLAG_CONSULT_UNAVAILABLE,
    FLAG_FEE_MISSING,
    FLAG_NO_SPEND,
    FLAG_SPEND_FALLBACK,
    FLAG_TICKET_FALLBACK,
    TYPE_KINDS,
    MeasuredRate,
    RateRange,
    RevenueContext,
    RevenueInput,
    practice_median_first_treatment_ticket,
    rate_range,
    revenue_basis,
    summarise_revenue,
    type_revenue,
    wilson,
)
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.runs import load_measured_rates

D = Decimal
CTX = RevenueContext(median_first_treatment_ticket_cents=30000)
NO_CTX = RevenueContext(median_first_treatment_ticket_cents=None)
S = ReactivationSettings()


def four_dp(x: Decimal) -> Decimal:
    return x.quantize(D("0.0001"))


# --- Wilson ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("booked", "contacted", "low", "high"),
    [
        (12, 100, "0.0700", "0.1981"),
        (0, 100, "0.0000", "0.0370"),
        (100, 100, "0.9630", "1.0000"),
        (1, 1, "0.2065", "1.0000"),
    ],
)
def test_wilson_known_values(booked, contacted, low, high):
    got_low, got_high = wilson(booked, contacted)
    assert (four_dp(got_low), four_dp(got_high)) == (D(low), D(high))


def test_wilson_is_clamped_ordered_and_symmetric():
    for contacted in (1, 2, 5, 30, 77, 100):
        for booked in range(0, contacted + 1, max(1, contacted // 7)):
            low, high = wilson(booked, contacted)
            assert D(0) <= low <= high <= D(1)
            mirror_low, mirror_high = wilson(contacted - booked, contacted)
            assert abs(low - (1 - mirror_high)) < D("1e-20") and abs(high - (1 - mirror_low)) < D("1e-20")


def test_wilson_clamps_booked_to_contacted_and_rejects_nobody_contacted():
    assert wilson(500, 100) == wilson(100, 100) and wilson(-3, 100) == wilson(0, 100)
    with pytest.raises(ValueError, match="at least 1"):
        wilson(0, 0)


# --- rates -----------------------------------------------------------------------------------


def test_assumed_below_the_sample_and_measured_at_it():
    assumed = rate_range("one_and_done", {"one_and_done": MeasuredRate(booked=10, contacted=29)}, S)
    assert assumed == RateRange(D("0.0800"), D("0.1500"), "assumed")
    measured = rate_range("one_and_done", {"one_and_done": MeasuredRate(booked=9, contacted=30)}, S)
    low, high = wilson(9, 30)
    assert measured.source == "measured"
    assert measured.low <= low and measured.high >= high  # quantised outwards, never narrower
    assert measured.low == low.quantize(D("0.0001"), rounding="ROUND_FLOOR")
    assert measured.high == high.quantize(D("0.0001"), rounding="ROUND_CEILING")


def test_each_type_uses_only_its_own_measured_rate():
    measured = {"one_and_done": MeasuredRate(9, 30)}
    assert rate_range("lapsed_high_value", measured, S).source == "assumed"
    assert rate_range("one_and_done", measured, S).source == "measured"
    assert rate_range("one_and_done", None, S).source == "assumed"


def test_min_sample_comes_from_settings():
    cfg = S.model_copy(update={"revenue": S.revenue.model_copy(update={"min_sample": 10})})
    assert rate_range("one_and_done", {"one_and_done": MeasuredRate(1, 10)}, cfg).source == "measured"
    assert rate_range("one_and_done", {"one_and_done": MeasuredRate(1, 9)}, cfg).source == "assumed"


def test_a_retention_type_has_no_return_rate():
    r = rate_range("unused_balance", {"unused_balance": MeasuredRate(30, 100)}, S)
    assert r == RateRange(D("1.0000"), D("1.0000"), "assumed")


def test_rates_are_quantised_to_four_places_and_clamped():
    cfg = S.model_copy(update={"revenue": S.revenue.model_copy(update={"rate_low": 0.0, "rate_high": 1.0})})
    assert rate_range("lapsed_high_value", None, cfg) == RateRange(D("0.0000"), D("1.0000"), "assumed")
    perfect = rate_range("one_and_done", {"one_and_done": MeasuredRate(100, 100)}, S)
    assert perfect.high == D("1.0000") and D(0) <= perfect.low <= perfect.high


# --- type revenue and totals -----------------------------------------------------------------


def test_sum_cents_first_then_multiply_and_round_once():
    row = type_revenue("one_and_done", [1000, 2500], RateRange(D("0.0800"), D("0.1500"), "assumed"))
    assert (row.patient_count, row.basis_total_cents) == (2, 3500)
    assert (row.revenue_low_cents, row.revenue_high_cents) == (280, 525)
    assert row.revenue_kind == "new" and all(
        isinstance(v, int) for v in (row.revenue_low_cents, row.revenue_high_cents)
    )


def test_rounding_is_half_up_not_half_even():
    rate = RateRange(D("0.1000"), D("0.1000"), "assumed")
    assert type_revenue("one_and_done", [25], rate).revenue_low_cents == 3  # 2.5 -> 3 (half-even gives 2)
    assert type_revenue("one_and_done", [5], rate).revenue_low_cents == 1  # 0.5 -> 1
    assert type_revenue("one_and_done", [5], RateRange(D("0.0900"), D("0.0900"), "assumed")).revenue_low_cents == 0


def test_one_rounding_step_per_type_not_per_patient():
    rate = RateRange(D("0.0800"), D("0.0800"), "assumed")
    row = type_revenue("one_and_done", [6] * 10, rate)  # each 0.48 rounds to 0; together 4.8 -> 5
    assert row.revenue_low_cents == 5


def test_a_basis_of_zero_and_an_empty_type_are_handled():
    rate = RateRange(D("0.0800"), D("0.1500"), "assumed")
    zero = type_revenue("one_and_done", [0, 0], rate)
    assert (zero.patient_count, zero.basis_total_cents, zero.revenue_low_cents, zero.revenue_high_cents) == (2, 0, 0, 0)
    empty = type_revenue("one_and_done", [], rate)
    assert (empty.patient_count, empty.revenue_high_cents) == (0, 0)
    with pytest.raises(ValueError, match="negative"):
        type_revenue("one_and_done", [100, -1], rate)


def test_low_never_exceeds_high_for_any_rates_and_bases():
    rng = random.Random(1)
    for _ in range(300):
        low, high = sorted(D(rng.randint(0, 10000)) / D(10000) for _ in range(2))
        row = type_revenue(
            "one_and_done", [rng.randint(0, 500000) for _ in range(rng.randint(0, 6))], RateRange(low, high, "assumed")
        )
        assert 0 <= row.revenue_low_cents <= row.revenue_high_cents


# --- basis -----------------------------------------------------------------------------------


def test_basis_for_lapsed_high_value_is_the_average_ticket():
    assert revenue_basis("lapsed_high_value", blank(average_ticket_cents=40000), CTX, S).cents == 40000
    zero = revenue_basis("lapsed_high_value", blank(average_ticket_cents=0), CTX, S)
    assert (zero.cents, zero.flags) == (0, (FLAG_NO_SPEND,))


def test_basis_for_churned_member_is_fee_times_months():
    assert revenue_basis("churned_member", blank(latest_membership_fee_cents=9900), CTX, S).cents == 59400
    months = S.model_copy(
        update={
            "types": S.types.model_copy(
                update={"churned_member": S.types.churned_member.model_copy(update={"membership_months": 3})}
            )
        }
    )
    assert revenue_basis("churned_member", blank(latest_membership_fee_cents=9900), CTX, months).cents == 29700
    for fee in (None, 0, -5):
        b = revenue_basis("churned_member", blank(latest_membership_fee_cents=fee), CTX, S)
        assert (b.cents, b.flags) == (0, (FLAG_FEE_MISSING,))


def test_consult_basis_is_the_quote_then_the_practice_median_never_the_consult_fee():
    assert revenue_basis("consult_not_converted", blank(quoted_plan_cents=250000), CTX, S).cents == 250000
    assert revenue_basis("consult_not_converted", blank(quoted_plan_cents=None), CTX, S).cents == 30000
    paid_only_the_fee = blank(
        spend_cents=5000,
        ticket_total_cents=5000,
        average_ticket_cents=5000,
        first_visit_ticket_cents=5000,
        quoted_plan_cents=None,
    )
    assert revenue_basis("consult_not_converted", paid_only_the_fee, CTX, S).cents == 30000
    nothing = revenue_basis("consult_not_converted", paid_only_the_fee, NO_CTX, S)
    assert (nothing.cents, nothing.flags) == (0, (FLAG_CONSULT_UNAVAILABLE,))


def test_overdue_maintenance_uses_the_usual_service_ticket_else_the_patients_average():
    f = blank(usual_service_ticket_total_cents=90000, usual_service_visit_days=3, average_ticket_cents=1)
    assert revenue_basis("overdue_maintenance", f, CTX, S).cents == 30000
    half = blank(usual_service_ticket_total_cents=5, usual_service_visit_days=2)
    assert revenue_basis("overdue_maintenance", half, CTX, S).cents == 3  # 2.5 rounds half up
    fallback = revenue_basis(
        "overdue_maintenance", blank(usual_service_ticket_total_cents=None, average_ticket_cents=42000), CTX, S
    )
    assert (fallback.cents, fallback.flags) == (42000, (FLAG_TICKET_FALLBACK,))
    none = revenue_basis(
        "overdue_maintenance", blank(usual_service_ticket_total_cents=0, average_ticket_cents=0), CTX, S
    )
    assert (none.cents, none.flags) == (0, (FLAG_NO_SPEND,))


def test_one_and_done_uses_the_visit_ticket_else_spend():
    assert revenue_basis("one_and_done", blank(first_visit_ticket_cents=20000, spend_cents=99), CTX, S).cents == 20000
    fallback = revenue_basis("one_and_done", blank(first_visit_ticket_cents=None, spend_cents=15000), CTX, S)
    assert (fallback.cents, fallback.flags) == (15000, (FLAG_SPEND_FALLBACK,))
    nothing = revenue_basis("one_and_done", blank(first_visit_ticket_cents=None, spend_cents=0), CTX, S)
    assert (nothing.cents, nothing.flags) == (0, (FLAG_NO_SPEND,))


def test_unused_balance_basis_is_the_balance_and_is_retention():
    b = revenue_basis("unused_balance", blank(prepaid_balance_cents=7000), CTX, S)
    assert (b.cents, b.kind) == (7000, "retention")
    assert {k for k, v in TYPE_KINDS.items() if v == "retention"} == {"unused_balance"}
    with pytest.raises(ValueError, match="unknown patient type"):
        revenue_basis("nope", blank(), CTX, S)


def test_practice_median_first_treatment_ticket():
    facts = lambda *vals: [blank(first_treatment_ticket_cents=v) for v in vals]  # noqa: E731
    assert practice_median_first_treatment_ticket(facts(100, 300, 200)) == 200
    assert practice_median_first_treatment_ticket(facts(100, 201)) == 151  # even count: half up
    assert practice_median_first_treatment_ticket(facts(None, 0, 500)) == 500  # None and 0 are not prices
    assert practice_median_first_treatment_ticket(facts(None, 0)) is None
    assert practice_median_first_treatment_ticket([]) is None


# --- run summary -----------------------------------------------------------------------------


def _inputs() -> list[RevenueInput]:
    d = "dormant"
    return [
        RevenueInput(blank(first_visit_ticket_cents=20000), d, "one_and_done", ("one_and_done",)),
        RevenueInput(blank(first_visit_ticket_cents=30000), d, "one_and_done", ("one_and_done",)),
        RevenueInput(blank(average_ticket_cents=50000), d, "lapsed_high_value", ("lapsed_high_value",)),
        # primary one_and_done with a balance: new revenue under its primary type, balance in retention only
        RevenueInput(
            blank(first_visit_ticket_cents=10000, prepaid_balance_cents=7000),
            d,
            "one_and_done",
            ("one_and_done", "unused_balance"),
        ),
        RevenueInput(blank(prepaid_balance_cents=3000), d, "unused_balance", ("unused_balance",)),
        RevenueInput(blank(average_ticket_cents=12000), "at_risk", None, ()),
        RevenueInput(blank(prepaid_balance_cents=999), "active", None, ()),  # not dormant: ignored
        RevenueInput(blank(average_ticket_cents=8000), d, None, ()),  # unclassified: no basis
        RevenueInput(blank(first_visit_ticket_cents=0, spend_cents=0), d, "one_and_done", ("one_and_done",)),
    ]


def test_summary_rows_totals_and_separate_figures():
    summary = summarise_revenue(_inputs(), CTX, S)
    rows = {r.type_key: r for r in summary.rows}
    assert [r.type_key for r in summary.rows] == [
        "lapsed_high_value",
        "churned_member",
        "consult_not_converted",
        "overdue_maintenance",
        "lapsed_regular",
        "one_and_done",
        "unused_balance",
    ]
    one = rows["one_and_done"]
    assert (one.patient_count, one.basis_total_cents) == (4, 60000)  # 20000 + 30000 + 10000 + a zero basis
    assert (one.revenue_low_cents, one.revenue_high_cents) == (4800, 9000)
    assert (rows["lapsed_high_value"].revenue_low_cents, rows["lapsed_high_value"].revenue_high_cents) == (4000, 7500)
    assert rows["churned_member"].patient_count == 0 and rows["churned_member"].revenue_high_cents == 0
    # retention: rows by primary type; the separate figure covers every dormant patient with a balance
    unused = rows["unused_balance"]
    assert (unused.patient_count, unused.basis_total_cents, unused.revenue_kind) == (1, 3000, "retention")
    assert (unused.revenue_low_cents, unused.revenue_high_cents, unused.rate_low, unused.rate_high) == (
        3000,
        3000,
        D("1.0000"),
        D("1.0000"),
    )
    assert summary.retention_cents == 7000 + 3000
    # never mixed: new totals are exactly the new rows, with no balance in them
    new_rows = [r for r in summary.rows if r.revenue_kind == "new"]
    assert summary.new_low_cents == sum(r.revenue_low_cents for r in new_rows) == 8800
    assert summary.new_high_cents == sum(r.revenue_high_cents for r in new_rows) == 16500
    assert summary.at_risk_revenue_cents == 12000  # D7: shown on its own, not multiplied, not added
    assert summary.zero_basis_patients == 1 and summary.flag_counts == {FLAG_NO_SPEND: 1}


def test_money_in_a_summary_is_all_integer():
    summary = summarise_revenue(_inputs(), CTX, S)
    ints = [summary.new_low_cents, summary.new_high_cents, summary.retention_cents, summary.at_risk_revenue_cents]
    for r in summary.rows:
        ints += [r.basis_total_cents, r.revenue_low_cents, r.revenue_high_cents]
        assert r.revenue_low_cents <= r.revenue_high_cents and r.rate_low <= r.rate_high
    assert all(type(v) is int for v in ints)


def test_the_total_always_equals_the_sum_of_the_rounded_rows():
    rng = random.Random(42)
    keys = [k for k in TYPE_KINDS if k != "unused_balance"]
    for _ in range(40):
        inputs = [
            RevenueInput(
                blank(
                    average_ticket_cents=rng.randint(0, 90000),
                    first_visit_ticket_cents=rng.randint(0, 90000),
                    usual_service_ticket_total_cents=rng.randint(0, 99999),
                    usual_service_visit_days=rng.randint(1, 9),
                    latest_membership_fee_cents=rng.choice([None, 0, 4900]),
                    quoted_plan_cents=rng.choice([None, 12345]),
                ),
                "dormant",
                (key := rng.choice(keys)),
                (key,),
            )
            for _ in range(rng.randint(0, 30))
        ]
        measured = {k: MeasuredRate(rng.randint(0, 40), rng.randint(30, 80)) for k in keys if rng.random() < 0.5}
        summary = summarise_revenue(inputs, CTX, S, measured)
        new_rows = [r for r in summary.rows if r.revenue_kind == "new"]
        assert summary.new_low_cents == sum(r.revenue_low_cents for r in new_rows)
        assert summary.new_high_cents == sum(r.revenue_high_cents for r in new_rows)
        assert summary.new_low_cents <= summary.new_high_cents


def test_disabled_types_have_no_row_and_their_patients_add_nothing():
    off = S.model_copy(
        update={
            "types": S.types.model_copy(
                update={
                    "one_and_done": S.types.one_and_done.model_copy(update={"enabled": False}),
                    "unused_balance": S.types.unused_balance.model_copy(update={"enabled": False}),
                }
            )
        }
    )
    summary = summarise_revenue(_inputs(), CTX, off)
    keys = [r.type_key for r in summary.rows]
    assert "one_and_done" not in keys and "unused_balance" not in keys
    assert summary.retention_cents == 7000 + 3000  # matched_types decides; the engine drops a disabled type from it
    all_off = S.model_copy(
        update={
            "types": S.types.model_copy(
                update={k: getattr(S.types, k).model_copy(update={"enabled": False}) for k in TYPE_KINDS}
            )
        }
    )
    empty = summarise_revenue(_inputs(), CTX, all_off)
    assert empty.rows == () and empty.new_low_cents == empty.new_high_cents == 0


def test_shuffling_the_input_gives_an_identical_summary():
    inputs = _inputs()
    shuffled = list(inputs)
    random.Random(7).shuffle(shuffled)
    assert summarise_revenue(shuffled, CTX, S) == summarise_revenue(inputs, CTX, S)


# --- measured rates from campaigns -----------------------------------------------------------


async def _seed_campaigns():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    p = [sc.patient(f"p{i}") for i in range(8)]
    await sc.save()
    launched = {"A": NOW - timedelta(days=40), "B": NOW - timedelta(days=60)}

    async with tenant_session(tenant) as s:

        def campaign(name, type_key, launched_at, audience=None):
            c = Campaign(
                tenant_id=tenant,
                name=name,
                criteria={},
                type_key=type_key,
                launched_at=launched_at,
                audience=audience,
                status="running" if launched_at else "draft",
            )
            s.add(c)
            return c

        def target(c, patient, status, booked_at=None):
            s.add(
                CampaignTarget(
                    tenant_id=tenant,
                    campaign_id=c.id,
                    patient_id=patient.id,
                    days_lapsed=100,
                    status=status,
                    booked_at=booked_at,
                )
            )

        a = campaign("A", "one_and_done", launched["A"])
        b = campaign("B", "one_and_done", launched["B"])
        elapsing = campaign("C", "lapsed_high_value", NOW - timedelta(days=10))  # window not elapsed
        untyped = campaign("D", None, NOW - timedelta(days=40))
        custom = campaign("E", "overdue_maintenance", NOW - timedelta(days=40), audience={"anything": True})
        draft = campaign("F", "consult_not_converted", None)
        edge = campaign("G", "churned_member", NOW - timedelta(days=30))  # window ends exactly now
        too_soon = campaign("H", "unused_balance", NOW - timedelta(days=30) + timedelta(minutes=1))
        await s.flush()

        target(a, p[0], "contacted")
        target(a, p[1], "booked", launched["A"] + timedelta(days=5))
        target(a, p[2], "booked", launched["A"] + timedelta(days=35))  # booked after the window closed
        target(a, p[3], "opted_out")
        target(a, p[4], "pending")
        target(b, p[1], "booked", launched["B"] + timedelta(days=10))  # booked twice: counts once
        target(b, p[5], "booked", launched["B"] + timedelta(days=3))
        target(b, p[6], "contacted")
        for c in (elapsing, untyped, custom, draft, too_soon):
            target(c, p[0], "booked", NOW - timedelta(days=5))
            target(c, p[1], "contacted")
        target(edge, p[0], "contacted")
        # a booking recorded before the launch is not an attributed booking
        target(edge, p[7], "booked", edge.launched_at - timedelta(days=1))
    return tenant


async def test_measured_rates_from_seeded_campaigns():
    tenant = await _seed_campaigns()
    async with tenant_session(tenant) as s:
        rates = await load_measured_rates(s, NOW, 30)
    assert rates == {
        "one_and_done": MeasuredRate(booked=2, contacted=5),
        "churned_member": MeasuredRate(booked=0, contacted=2),
    }


async def test_nothing_is_measured_while_every_window_is_still_open():
    tenant = await _seed_campaigns()
    async with tenant_session(tenant) as s:
        assert await load_measured_rates(s, NOW, 90) == {}


async def test_another_tenants_campaigns_never_leak_in():
    mine, other = await _seed_campaigns(), await _seed_campaigns()
    async with tenant_session(mine) as s:
        assert (await load_measured_rates(s, NOW, 30))["one_and_done"] == MeasuredRate(booked=2, contacted=5)
    async with tenant_session(other) as s:
        assert (await load_measured_rates(s, NOW, 30))["one_and_done"] == MeasuredRate(booked=2, contacted=5)
    empty = await create_test_tenant()
    async with tenant_session(empty) as s:
        assert await load_measured_rates(s, NOW, 30) == {}


async def test_load_measured_rates_needs_an_aware_now():
    tenant = await create_test_tenant()
    async with tenant_session(tenant) as s:
        with pytest.raises(ValueError, match="timezone-aware"):
            await load_measured_rates(s, datetime(2026, 6, 1, 15), 30)
    assert UTC is not None


async def test_no_audience_counts_whether_it_is_sql_null_or_json_null():
    tenant = await create_test_tenant()
    sc = Scene(tenant)
    p = [sc.patient(f"p{i}") for i in range(3)]
    await sc.save()
    launched = NOW - timedelta(days=40)
    async with tenant_session(tenant) as s:
        sql_null = Campaign(tenant_id=tenant, name="a", criteria={}, type_key="one_and_done", launched_at=launched)
        json_null = Campaign(
            tenant_id=tenant, name="b", criteria={}, type_key="one_and_done", launched_at=launched, audience=None
        )
        empty_object = Campaign(
            tenant_id=tenant, name="c", criteria={}, type_key="one_and_done", launched_at=launched, audience={}
        )
        s.add_all([sql_null, json_null, empty_object])
        await s.flush()
        for campaign, patient in ((sql_null, p[0]), (json_null, p[1]), (empty_object, p[2])):
            s.add(
                CampaignTarget(
                    tenant_id=tenant,
                    campaign_id=campaign.id,
                    patient_id=patient.id,
                    days_lapsed=100,
                    status="contacted",
                )
            )
    async with tenant_session(tenant) as s:
        # the campaign with an (empty) audience object is customised, so only the two others count
        assert await load_measured_rates(s, NOW, 30) == {"one_and_done": MeasuredRate(booked=0, contacted=2)}
