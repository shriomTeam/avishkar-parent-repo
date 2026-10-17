import json
import os
import random
import uuid
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from builders import blank
from factories import NOW, TZ, build_messy_tenant
from golden import SERVICE_NAMES, TODAY, N, golden_facts, golden_inputs, pid

from clinic_core.database import tenant_session
from clinic_reactivation.analysis import engine
from clinic_reactivation.analysis.engine import RunFailed, analyse
from clinic_reactivation.analysis.exclusions import FlagValue
from clinic_reactivation.analysis.facts import load_facts
from clinic_reactivation.analysis.revenue import MeasuredRate
from clinic_reactivation.analysis.scoring import PastResponse
from clinic_reactivation.analysis.settings import ReactivationSettings

S = ReactivationSettings()
SNAPSHOT = Path(__file__).parent / "snapshots" / "golden_run_result.json"
TYPE_KEYS = [
    "lapsed_high_value",
    "churned_member",
    "consult_not_converted",
    "overdue_maintenance",
    "lapsed_regular",  # priority 5 ties with one_and_done; a tie sorts by type key
    "one_and_done",
    "unused_balance",
]


def fx(i: int, days: int = 130, *, visits: int = 3, spend: int | None = None, **kw):
    """A scored patient, `days` clinic-local days since the last visit."""
    kw.setdefault("usual_service_visit_days", 1)
    spend = 1000 + 37 * i if spend is None else spend
    return blank(
        patient_id=pid(i), visit_count=visits, last_visit_day=TODAY - timedelta(days=days), spend_cents=spend,
        ticket_total_cents=spend, average_ticket_cents=spend // visits,
        first_visit_day=TODAY - timedelta(days=days + 90),
        visit_days=(TODAY - timedelta(days=days),), visit_starts=(datetime(2026, 1, 5, 15, tzinfo=NOW.tzinfo),), **kw,
    )  # fmt: skip


def run(facts, settings=S, *, measured=None, responders=None, previous=None, names=None, **kw):
    return analyse(
        facts, settings, measured or {}, responders or {}, previous, NOW, TZ, service_names=names, **kw
    )  # fmt: skip


def off(settings, **groups):
    return settings.model_copy(update=groups)


def disable(settings, *keys):
    types = settings.types.model_copy(
        update={k: getattr(settings.types, k).model_copy(update={"enabled": False}) for k in keys}
    )
    return settings.model_copy(update={"types": types})


# --- the edge cases --------------------------------------------------------------------------


def test_an_empty_tenant_completes_with_the_no_patients_warning():
    r = run([])
    assert r.patients == () and r.quality["warnings"] == ["no_patients"]
    assert r.summary["patients_total"] == 0 and r.summary["dormant_count"] == 0
    assert [t.type_key for t in r.types] == TYPE_KEYS and all(t.patient_count == 0 for t in r.types)
    assert r.summary["new_revenue_low_cents"] == r.summary["new_revenue_high_cents"] == 0
    assert r.summary["first_run"] is True


def test_every_patient_excluded():
    deceased = [fx(i, deceased=FlagValue.TRUE) for i in range(30)]
    r = run(deceased)
    assert r.patients == () and r.summary["patients_scored"] == 0 and r.summary["patients_excluded"] == 30
    assert r.quality["excluded_deceased"]["count"] == 30 and r.summary["dormant_count"] == 0
    assert r.quality["warnings"] == [] and r.quality["spend_cohort_size"] == 0


def test_all_types_disabled_still_completes():
    s = disable(S, *TYPE_KEYS)
    r = run([fx(i, 130 + i) for i in range(30)], s)
    assert r.types == () and "no_types_enabled" in r.quality["warnings"]
    assert r.summary["dormant_count"] == 30 and r.summary["unclassified_dormant"] == 30
    assert r.summary["new_revenue_high_cents"] == 0 and r.summary["retention_value_cents"] == 0
    assert all(row.primary_type is None for row in r.patients)


def test_a_corrupt_patient_is_isolated_and_counted():
    good = [fx(i, 130 + i) for i in range(100)]
    bad = replace(fx(500, 200), spend_cents=None)
    r = run([*good, bad])
    assert r.summary["patients_total"] == 101 and r.summary["patients_scored"] == 100
    assert r.quality["patient_errors"] == {
        "count": 1,
        "items": [{"patient_id": str(pid(500)), "error_class": "CorruptFacts"}],
    }
    clean = run(good)
    assert r.patients == clean.patients and r.types == clean.types  # everyone else is unaffected
    assert r.summary["patients_errored"] == 1 and clean.summary["patients_errored"] == 0


def test_the_error_record_carries_no_patient_data():
    bad = replace(fx(1, 200), spend_cents="not a number", last_visit_day="yesterday")
    r = run([bad, *[fx(i, 130) for i in range(2, 80)]])
    item = r.quality["patient_errors"]["items"][0]
    assert set(item) == {"patient_id", "error_class"}


def test_a_failure_while_scoring_recomputes_the_spend_cohort_without_that_patient(monkeypatch):
    # the highest spender raises while being classified; the others must be scored exactly as if that patient
    # had never been there, which includes their percentiles
    patients = [fx(i, 250, visits=4, spend=i * 100, spend_percentile=None) for i in range(1, 61)]
    victim = pid(60)
    real = engine.classify

    def flaky(f, settings, now, tz_name):
        if f.patient_id == victim:
            raise RuntimeError("boom")
        return real(f, settings, now, tz_name)

    monkeypatch.setattr(engine, "classify", flaky)
    broken = run(patients)
    monkeypatch.setattr(engine, "classify", real)
    clean = run(patients[:-1])
    assert broken.quality["patient_errors"]["items"] == [{"patient_id": str(victim), "error_class": "RuntimeError"}]
    assert broken.patients == clean.patients and broken.types == clean.types
    top = max(clean.patients, key=lambda r: r.total_spend_cents)
    assert top.primary_type == "lapsed_high_value"


@pytest.mark.parametrize(("corrupt", "fails"), [(6, False), (7, True), (9, True)])
def test_more_than_two_percent_corrupt_fails_the_run(corrupt, fails):
    patients = [fx(i, 130) for i in range(300 - corrupt)] + [
        replace(fx(1000 + i), spend_cents=None) for i in range(corrupt)
    ]
    if fails:
        with pytest.raises(RunFailed) as caught:
            run(patients)
        assert caught.value.error_code == "too_many_patient_errors"
        assert str(pid(1000)) not in caught.value.detail  # no patient ids in the message
    else:
        assert run(patients).summary["patients_errored"] == 6  # exactly 2% is within the limit


def test_the_error_tolerance_comes_from_settings():
    strict = off(S, limits=S.limits.model_copy(update={"patient_error_tolerance": 0}))
    with pytest.raises(RunFailed):
        run([fx(1), replace(fx(2), spend_cents=None)], strict)
    assert run([fx(1), fx(2)], strict).summary["patients_errored"] == 0


def test_a_patient_with_a_future_booking_is_never_dormant():
    rng = random.Random(1)
    patients = [
        fx(i, rng.randint(0, 600), visits=rng.choice([1, 2, 5]), has_future_booking=True, prepaid_balance_cents=500)
        for i in range(40)
    ]
    r = run(patients)
    assert r.patients == () and r.summary["dormant_count"] == r.summary["at_risk_count"] == 0
    assert r.summary["active_count"] == 40


def test_totals_equal_the_sum_of_the_types():
    r = run(golden_facts(), measured=golden_inputs()[0])
    new_rows = [t for t in r.types if t.revenue_kind == "new"]
    assert r.summary["new_revenue_low_cents"] == sum(t.revenue_low_cents for t in new_rows)
    assert r.summary["new_revenue_high_cents"] == sum(t.revenue_high_cents for t in new_rows)
    retention = [t for t in r.types if t.revenue_kind == "retention"]
    assert [t.type_key for t in retention] == ["unused_balance"]
    assert (
        r.summary["retention_value_cents"] >= retention[0].revenue_low_cents
    )  # all dormant balances, not just primary
    assert sum(t.patient_count for t in r.types) + r.summary["unclassified_dormant"] == r.summary["dormant_count"]


def test_shuffling_the_input_gives_byte_identical_output():
    measured, responders, previous, _, _ = golden_inputs()
    base = run(golden_facts(), measured=measured, responders=responders, previous=previous, names=SERVICE_NAMES)
    for seed in range(4):
        shuffled = golden_facts()
        random.Random(seed).shuffle(shuffled)
        again = run(shuffled, measured=measured, responders=responders, previous=previous, names=SERVICE_NAMES)
        assert again.canonical_json() == base.canonical_json()


def test_running_twice_gives_identical_output():
    a, b = run(golden_facts()), run(golden_facts())
    assert a == b and a.canonical_json() == b.canonical_json() and a.digest() == b.digest()


def test_data_looks_incomplete_when_most_patients_have_no_completed_visits():
    no_visits = lambda i: blank(patient_id=pid(i), visit_count=0)  # noqa: E731
    six_of_ten = [no_visits(i) for i in range(6)] + [fx(i) for i in range(6, 10)]
    assert "data_looks_incomplete" in run(six_of_ten).quality["warnings"]
    five_of_ten = [no_visits(i) for i in range(5)] + [fx(i) for i in range(5, 10)]
    assert "data_looks_incomplete" not in run(five_of_ten).quality["warnings"]  # exactly half is not "above"
    assert run(six_of_ten).quality["no_completed_visits"]["count"] == 6


def test_appointment_status_not_maintained_when_many_past_appointments_are_still_booked():
    stale = lambda n: [fx(i, past_appointments=10, stale_booked_in_past=n) for i in range(40)]  # noqa: E731
    assert "appointment_status_not_maintained" in run(stale(4)).quality["warnings"]  # 40%
    assert "appointment_status_not_maintained" not in run(stale(3)).quality["warnings"]  # exactly 30%


def test_cohort_too_small_warns_only_when_lapsed_high_value_is_enabled():
    few = [fx(i, 130) for i in range(10)]
    assert "cohort_too_small_for_percentile" in run(few).quality["warnings"]
    assert "cohort_too_small_for_percentile" not in run(few, disable(S, "lapsed_high_value")).quality["warnings"]
    assert "cohort_too_small_for_percentile" not in run([fx(i, 130) for i in range(25)]).quality["warnings"]
    assert run(few).quality["spend_cohort_size"] == 10


def test_unusable_inputs_fail_before_any_work():
    with pytest.raises(RunFailed) as caught:
        analyse([fx(1)], S, {}, {}, None, NOW, "Mars/Olympus")
    assert caught.value.error_code == "bad_timezone"
    with pytest.raises(ValueError, match="timezone-aware"):
        analyse([fx(1)], S, {}, {}, None, datetime(2026, 6, 1, 15), TZ)
    with pytest.raises(RunFailed) as dup:
        run([fx(1), fx(1)])
    assert dup.value.error_code == "invariant_failed"


# --- what comes out --------------------------------------------------------------------------


def test_reasons_are_short_plain_english_with_the_service_name_when_known():
    service = uuid.UUID(int=0x1000)
    f = fx(1, 214, visits=3, usual_service_id=service)
    named = run([f], names={service: "Botox"}).patients[0]
    assert named.reasons[0] == "Last visit 214 days ago, usual Botox every 120 days"
    assert run([f]).patients[0].reasons[0] == "Last visit 214 days ago, usual service every 120 days"
    assert (
        run([fx(2, 214, usual_service_id=None)]).patients[0].reasons[0].startswith("Last visit 214 days ago, standard")
    )
    unclassified = run([f], disable(S, "lapsed_regular")).patients[0]  # a repeat patient is otherwise a regular
    assert unclassified.primary_type is None and unclassified.reasons[-1].startswith("Dormant, but matches none")
    one = run([fx(3, 100, visits=1)]).patients[0]
    assert one.primary_type == "one_and_done" and "Only one visit, 100 days ago." in one.reasons
    soon = run([fx(4, 110)]).patients[0]
    assert soon.status == "at_risk" and soon.reasons[0].endswith("due again soon")


def test_rows_follow_the_ordering_rule():
    r = run(golden_facts(), responders=golden_inputs()[1])
    keys = [(-p.likelihood_score, -p.total_spend_cents, p.patient_id.int) for p in r.patients]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_only_dormant_and_at_risk_patients_get_rows_and_active_ones_do_not():
    r = run(golden_facts())
    assert {p.status for p in r.patients} == {"dormant", "at_risk"}
    assert len(r.patients) == r.summary["dormant_count"] + r.summary["at_risk_count"]
    assert r.summary["active_count"] > 0


def test_disabled_points_are_absent_from_the_rows_and_the_summary():
    s = off(S, points=S.points.model_copy(update={"best_time": False, "revenue_at_risk": False}))
    r = run(golden_facts(), s)
    assert all("best_time" not in p.points for p in r.patients)
    assert "best_time" in run(golden_facts()).patients[0].points
    assert "at_risk_revenue_cents" not in r.summary and "at_risk_revenue_cents" in run(golden_facts()).summary
    none = off(S, points=S.points.model_copy(update={k: False for k in S.points.model_dump()}))
    assert all(p.points == {} and p.change is None for p in run(golden_facts(), none).patients)


def test_change_since_last_first_run_and_against_a_previous_run():
    patients = [fx(i, 130 + i) for i in range(1, 11)]  # all dormant
    first = run(patients)
    assert first.summary["first_run"] is True and {p.change for p in first.patients} == {"first_run"}
    assert first.summary["newly_dormant"] == 0
    gone = pid(99)  # was dormant before and is not in this run at all (say, now excluded): has not come back
    second = run(patients, previous={pid(1), pid(2), gone})
    assert second.summary["first_run"] is False and second.summary["newly_dormant"] == 8
    assert second.summary["unchanged_dormant"] == 2 and second.summary["returned_since_last"] == 0
    came_back = run([fx(1, 20), *patients[1:]], previous={pid(1)})
    assert came_back.summary["returned_since_last"] == 1  # now active, and scored
    excluded_now = run([fx(1, 200, deceased=FlagValue.TRUE), *patients[1:]], previous={pid(1)})
    assert excluded_now.summary["returned_since_last"] == 0


def test_measured_rate_replaces_the_assumed_range_at_30_contacted():
    patients = [fx(i, 100, visits=1, first_visit_ticket_cents=10000) for i in range(30)]
    assumed = run(patients, measured={"one_and_done": MeasuredRate(5, 29)})
    measured = run(patients, measured={"one_and_done": MeasuredRate(5, 30)})
    pick = lambda r: next(t for t in r.types if t.type_key == "one_and_done")  # noqa: E731
    assert pick(assumed).rate_source == "assumed" and pick(measured).rate_source == "measured"
    assert pick(assumed).basis_total_cents == pick(measured).basis_total_cents == 300000


def test_past_responses_change_the_score_and_an_absent_patient_is_never_contacted():
    f = fx(1, 130, visits=4)
    never = run([f]).patients[0].likelihood_score
    booked = run([f], responders={pid(1): PastResponse.BOOKED}).patients[0].likelihood_score
    not_booked = run([f], responders={pid(1): "not_booked"}).patients[0].likelihood_score
    assert not_booked < never < booked
    assert 0 <= not_booked and booked <= 100 and (booked - never) == 8  # 0.15 * 0.5 * 100 = 7.5 -> 8 with rounding
    with pytest.raises(RunFailed):  # an unknown response is one corrupt patient, and one of one is over the limit
        run([f], responders={pid(1): "maybe"})


def test_the_quality_report_has_the_spec_keys_and_samples_are_capped():
    r = run([fx(i, 130, duplicate_appointments=2, stale_booked_in_past=1, past_appointments=9) for i in range(50)])
    q = r.quality
    for key in (
        "patients_total",
        "patients_scored",
        "excluded_minor",
        "excluded_do_not_contact",
        "excluded_deceased",
        "excluded_inactive",
        "no_completed_visits",
        "completed_in_future",
        "stale_booked_in_past",
        "duplicate_appointments",
        "unknown_appointment_status",
        "null_amount_transactions",
        "negative_spend_patients",
        "zero_basis_patients",
        "outlier_amounts",
        "missing_service_on_visits",
        "invalid_rebooking_interval",
        "invalid_dob",
        "unparsable_exclusion_flag",
        "naive_timestamps",
        "unclassified_dormant",
        "patient_errors",
        "data_available",
        "warnings",
    ):
        assert key in q, key
    assert q["duplicate_appointments"]["count"] == 100 and q["duplicate_appointments"]["patients"] == 50
    assert len(q["duplicate_appointments"]["sample_ids"]) == 20
    assert q["duplicate_appointments"]["sample_ids"] == sorted(q["duplicate_appointments"]["sample_ids"])
    assert q["exclusion_flags_not_importable"] is True and q["currency_assumed"] == "USD"
    assert set(q["data_available"]) == {"staff", "memberships", "consents", "services"}


def test_unknown_statuses_and_outliers_are_reported_per_value():
    r = run([
        fx(1, 130, unknown_appointment_status={"weird": 2}, unknown_membership_status={"paused": 1},
           outlier_transactions=3),
        fx(2, 130, unknown_appointment_status={"weird": 1, "odd": 1}),
    ])  # fmt: skip
    q = r.quality
    assert (
        q["unknown_appointment_status"]["weird"]["count"] == 3 and q["unknown_appointment_status"]["odd"]["count"] == 1
    )
    assert q["unknown_membership_status"]["paused"]["patients"] == 1
    assert q["outlier_amounts"]["count"] == 3


def test_exclusions_are_counted_by_one_reason_and_add_up():
    r = run(golden_facts())
    q, s = r.quality, r.summary
    counted = sum(q[k]["count"] for k in ("excluded_deceased", "excluded_do_not_contact", "unparsable_exclusion_flag",
                                          "excluded_minor", "no_completed_visits"))  # fmt: skip
    assert counted == s["patients_excluded"] and s["patients_total"] == N
    assert s["patients_total"] == s["patients_scored"] + s["patients_excluded"] + s["patients_errored"]


# --- the invariants --------------------------------------------------------------------------


def _built(facts=None):
    facts = facts if facts is not None else golden_facts()
    m, r, p, now, tz = golden_inputs()
    return engine._build(facts, S, m, r, p, now, tz, SERVICE_NAMES)


def test_a_normal_run_passes_every_invariant():
    result, internal = _built()
    assert engine._invariant_failures(result, internal) == []


def test_invariant_1_every_patient_is_accounted_for():
    result, internal = _built()
    internal.total += 1
    assert 1 in engine._invariant_failures(result, internal)


def test_invariant_2_dormant_count_and_the_types_add_up():
    result, internal = _built()
    broken = replace(result, summary={**result.summary, "dormant_count": result.summary["dormant_count"] + 1})
    assert 2 in engine._invariant_failures(broken, internal)
    broken = replace(
        result, summary={**result.summary, "unclassified_dormant": result.summary["unclassified_dormant"] + 1}
    )
    assert 2 in engine._invariant_failures(broken, internal)


def test_invariant_3_one_status_and_the_primary_is_among_the_matches():
    result, internal = _built()
    first = internal.scored[0]
    internal.scored[0] = replace(first, classification=replace(first.classification, status="odd"))
    assert 3 in engine._invariant_failures(result, internal)
    result, internal = _built()
    broken_row = replace(result.patients[0], primary_type="one_and_done", matched_types=("unused_balance",))
    assert 3 in engine._invariant_failures(replace(result, patients=(broken_row, *result.patients[1:])), internal)


def test_invariant_4_money_is_integer_and_totals_are_the_sum_of_the_rows():
    result, internal = _built()
    row = result.types[0]
    for broken in (
        replace(row, revenue_low_cents=row.revenue_high_cents + 1),
        replace(row, revenue_high_cents=-1),
        replace(row, basis_total_cents=1.5),
    ):
        assert 4 in engine._invariant_failures(replace(result, types=(broken, *result.types[1:])), internal)
    summary = {**result.summary, "new_revenue_low_cents": result.summary["new_revenue_low_cents"] + 1}
    assert 4 in engine._invariant_failures(replace(result, summary=summary), internal)


def test_invariant_5_scores_and_ids():
    result, internal = _built()
    for score in (101, -1, 50.0):
        row = replace(result.patients[0], likelihood_score=score)
        assert 5 in engine._invariant_failures(replace(result, patients=(row, *result.patients[1:])), internal)
    twice = (result.patients[0], result.patients[0], *result.patients[1:])
    assert 5 in engine._invariant_failures(replace(result, patients=twice), internal)


def test_invariant_6_nobody_with_a_future_booking_is_dormant_or_at_risk():
    result, internal = _built()
    i = next(n for n, s in enumerate(internal.scored) if s.classification.status == "dormant")
    s = internal.scored[i]
    internal.scored[i] = replace(s, facts=replace(s.facts, has_future_booking=True))
    assert 6 in engine._invariant_failures(result, internal)


def test_invariant_7_a_different_second_run_fails_the_run(monkeypatch):
    real, calls = engine._build, []

    def drifting(*args, **kwargs):
        result, internal = real(*args, **kwargs)
        calls.append(1)
        if len(calls) == 2:
            result = replace(result, summary={**result.summary, "as_of": "drifted"})
        return result, internal

    monkeypatch.setattr(engine, "_build", drifting)
    with pytest.raises(RunFailed) as caught:
        run(golden_facts())
    assert caught.value.error_code == "invariant_failed" and "7" in caught.value.detail


def test_determinism_check_can_be_turned_off(monkeypatch):
    real, calls = engine._build, []

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(engine, "_build", counting)
    run(golden_facts())
    assert len(calls) == 2
    calls.clear()
    run(golden_facts(), verify_determinism=False)
    assert len(calls) == 1


def test_a_broken_classification_fails_the_run_with_invariant_failed(monkeypatch):
    real = engine.classify

    def bad(f, settings, now, tz_name):
        c = real(f, settings, now, tz_name)
        return replace(c, status="dormant", reasons=("forced",)) if f.has_future_booking else c

    monkeypatch.setattr(engine, "classify", bad)
    with pytest.raises(RunFailed) as caught:
        run([fx(1, 130, has_future_booking=True)])
    assert caught.value.error_code == "invariant_failed" and "6" in caught.value.detail


# --- the golden run --------------------------------------------------------------------------


def _golden_result():
    measured, responders, previous, now, tz = golden_inputs()
    return analyse(
        golden_facts(), S, measured, responders, previous, now, tz, service_names=SERVICE_NAMES
    ).to_dict()  # fmt: skip


def test_the_golden_fixture_covers_what_the_snapshot_is_for():
    got = _golden_result()
    # unused_balance sits below lapsed_regular, so with default settings it is rarely a patient's primary type;
    # the golden fixture covers it through matched_types and the retention figure instead
    counted = {t["type_key"]: t["patient_count"] > 0 for t in got["types"]}
    assert counted == {**dict.fromkeys(TYPE_KEYS, True), "unused_balance": counted["unused_balance"]}
    assert any("unused_balance" in p["matched_types"] for p in got["patients"])
    assert got["summary"]["retention_value_cents"] > 0
    assert {t["rate_source"] for t in got["types"]} == {"assumed", "measured"}
    assert {p["status"] for p in got["patients"]} == {"dormant", "at_risk"}
    assert {p["change"] for p in got["patients"]} == {"new", "unchanged", "returned_since_last"}
    # D13: with default settings every general-rule-dormant patient is a lapsed regular (2+ visits) or one-and-done,
    # so none is unclassified here; that path is covered in test_types and by test_all_types_disabled_still_completes
    assert got["summary"]["unclassified_dormant"] == 0 and got["summary"]["patients_excluded"] > 0
    assert all(got["quality"][k]["count"] > 0 for k in ("duplicate_appointments", "outlier_amounts", "excluded_minor"))


def test_the_golden_run_matches_its_snapshot():
    got = _golden_result()
    if os.environ.get("UPDATE_GOLDEN"):
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(got, sort_keys=True, indent=1) + "\n")
    expected = json.loads(SNAPSHOT.read_text())
    if got != expected:
        diffs = [k for k in ("summary", "types", "quality") if got[k] != expected[k]]
        rows = sum(1 for a, b in zip(got["patients"], expected["patients"], strict=False) if a != b)
        pytest.fail(
            f"golden run changed: differs in {diffs or 'patients only'}; patient rows {len(got['patients'])} vs "
            f"{len(expected['patients'])}, {rows} rows differ. If this is intended, re-run with UPDATE_GOLDEN=1 "
            "and review the diff of tests/snapshots/golden_run_result.json."
        )


# --- from the database -----------------------------------------------------------------------


async def test_a_real_tenant_runs_end_to_end():
    messy = await build_messy_tenant()
    async with tenant_session(messy.tenant) as s:
        facts = await load_facts(s, NOW, TZ, cohort_min=S.limits.spend_cohort_minimum)
    r = analyse(facts, S, {}, {}, None, NOW, TZ)
    assert r.summary["patients_total"] == len(facts) and r.summary["patients_errored"] == 0
    assert r.summary["data_available"] == {"staff": True, "memberships": True, "consents": True, "services": True}
    assert r.quality["outlier_amounts"]["count"] == 1  # the one patient with a 99,000,000 cent transaction
