"""Browser-test helper for the Dormant patients pages. Touches ONLY the disposable TEST_* databases.

    uv run python packages/features/reactivation/scripts/browser_seed.py seed    --tenant-name NAME --scenario full
    uv run python packages/features/reactivation/scripts/browser_seed.py work    --tenant-name NAME
    uv run python packages/features/reactivation/scripts/browser_seed.py cleanup --tenant-name NAME

Scenarios for `seed`: full (a previous run plus this one, one type unavailable, one retention type), first (a
first analysis with nothing to compare with), failed (a completed run followed by a failed one), none (patients
but no runs), empty (no patients and no runs: the welcome page), large (one run of about `--patients N`
dormant patients, for scale measurements).
`work` plays the worker for the queued run the browser asked for. `cleanup` removes every run for the tenant and
every patient and service this script created. The workspace itself is created by the browser sign-in and is left
alone, like the other browser journeys.

Safety: it refuses to start unless TEST_DATABASE_URL and TEST_SYSTEM_DATABASE_URL are set, and refuses when
either points at the same database as the configured development DATABASE_* URLs (CI, whose database is
disposable, sets CI=true and may share a name). The DATABASE_* settings are then replaced with the TEST_* URLs for
this process, so nothing here can reach the development database. Prints one JSON line of facts for the test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from urllib.parse import urlsplit


def _target(url: str) -> tuple[str, int, str]:
    parts = urlsplit(url)
    return (parts.hostname or "", parts.port or 5432, parts.path.lstrip("/"))


def _guard() -> None:
    test_app, test_system = os.environ.get("TEST_DATABASE_URL"), os.environ.get("TEST_SYSTEM_DATABASE_URL")
    if not test_app or not test_system:
        sys.exit(
            "refusing to run: set TEST_DATABASE_URL and TEST_SYSTEM_DATABASE_URL to a disposable migrated database"
        )
    from clinic_core.settings import Settings  # reads DATABASE_* from the environment and the root .env

    dev = Settings()
    dev_targets = {_target(dev.database_url), _target(dev.database_system_url), _target(dev.database_auth_url)}
    if not os.environ.get("CI") and {_target(test_app), _target(test_system)} & dev_targets:
        sys.exit("refusing to run: a TEST_* URL points at the same database as the development DATABASE_* URLs")
    os.environ["DATABASE_URL"] = test_app
    os.environ["DATABASE_SYSTEM_URL"] = test_system
    os.environ["DATABASE_AUTH_URL"] = os.environ.get("TEST_AUTH_DATABASE_URL", test_app)
    from clinic_core.settings import get_settings

    get_settings.cache_clear()
    if get_settings().database_url != test_app or get_settings().database_system_url != test_system:
        sys.exit("refusing to run: could not point this process at the TEST_* databases")


_guard()

from datetime import UTC, datetime, timedelta  # noqa: E402

from sqlalchemy import delete, select  # noqa: E402

from clinic_core.database import dispose_engines, system_session, tenant_session  # noqa: E402
from clinic_db.models.core import Patient, Service, Tenant  # noqa: E402
from clinic_db.models.reactivation import Run, RunPatient, RunType  # noqa: E402
from clinic_reactivation.analysis.settings import ReactivationSettings  # noqa: E402
from clinic_reactivation.runs import execute_run  # noqa: E402

MARK = {"browser_seed": True}

# type_key, patients, basis cents, top service, kind, rate source
NEW_TYPES = [
    ("lapsed_high_value", 12, 6_000_000, "Filler", "assumed"),
    ("overdue_maintenance", 58, 9_280_000, "Neurotoxin", "assumed"),
    ("consult_not_converted", 34, 3_400_000, "Laser package", "measured"),
    ("lapsed_regular", 40, 5_600_000, "Neurotoxin", "assumed"),
    ("one_and_done", 27, 2_160_000, "Facial", "assumed"),
]
RETENTION = ("unused_balance", 9, 640_000, "Facial package")
UNCLASSIFIED = 0  # filled so the types add up to the dormant count


def _rates(source: str) -> tuple[float, float]:
    return (0.12, 0.2) if source == "measured" else (0.08, 0.15)


async def _tenant(name: str) -> Tenant:
    async with system_session() as s:
        tenant = (await s.scalars(select(Tenant).where(Tenant.name == name).order_by(Tenant.created_at.desc()))).first()
    if tenant is None:
        sys.exit(f"no workspace named {name!r} in the test database")
    return tenant


async def _wipe(tenant_id) -> None:
    async with tenant_session(tenant_id) as s:
        await s.execute(delete(Run))
        for model in (Patient, Service):
            await s.execute(delete(model).where(model.attributes.contains(MARK)))


def _quality() -> dict:
    return {
        "data_available": {"memberships": True, "staff": False, "consents": True, "services": True},
        "exclusion_flags_not_importable": True,
        "warnings": ["cohort_too_small_for_percentile"],
        "excluded_minor": {"count": 3, "patients": 3, "sample_ids": []},
        "no_completed_visits": {"count": 11, "patients": 11, "sample_ids": []},
        "patient_errors": {"count": 0, "items": []},
    }


FIRST = ["Maya", "Dan", "Priya", "Luis", "Hannah", "Omar", "Sofia", "Ethan", "Grace", "Noah", "Lena", "Victor"]
LAST = ["Rao", "Ortiz", "Shah", "Miller", "Chen", "Haddad", "Rossi", "Kim", "Okafor", "Lopez", "Novak", "Silva"]
SPECIAL = "Zelda Quillfeather"  # a name no other seeded patient has, for the search test


def _points(i: int, service_id) -> dict:
    email, sms = [(True, True), (True, False), (False, True), (False, False)][i % 4]
    return {
        "reachable": {"email": email, "sms": sms, "either": email or sms},
        "best_offer": {"service_id": str(service_id), "source": "usual_service"},
        "best_time": {"weekday": i % 7, "band": (i % 6) + 1, "visits_used": 4},
        "provider_continuity": {"status": ["active", "inactive", "unknown"][i % 3]},
        "change_since_last": {"change": "new" if i % 3 == 0 else "unchanged"},
    }


async def _seed_patients(tenant_id, run: Run, rows: list, services: dict, finished: datetime, at_risk: int) -> None:
    """One run-patient row per counted patient of every type (names, scores, reasons, points), so the
    patient list has something to show and every count on the Overview matches its list."""
    n = 0
    plan = [(r[0], r[1], r[2], r[9], r[8]) for r in rows]  # type, count, basis, top service, kind
    plan += [(None, UNCLASSIFIED_ROWS, 0, "Facial", "new")]
    async with tenant_session(tenant_id) as s:
        for key, count, basis, service, kind in plan:
            for i in range(count):
                n += 1
                name = (
                    SPECIAL
                    if (key == "overdue_maintenance" and i == 5)
                    else f"{FIRST[n % 12]} {LAST[(n // 12 + n) % 12]}"
                )
                first, _, last = name.partition(" ")
                patient = Patient(tenant_id=tenant_id, first_name=first, last_name=last, attributes=dict(MARK))
                s.add(patient)
                await s.flush()
                days = 120 + (n * 13) % 500
                s.add(
                    RunPatient(
                        tenant_id=tenant_id, run_id=run.id, patient_id=patient.id, status="dormant", primary_type=key,
                        matched_types=[key] if key else [], last_visit_at=finished - timedelta(days=days),
                        days_since_last_visit=days, overdue_ratio=round(1.1 + (n % 25) / 10, 2), visit_count=2 + n % 5,
                        total_spend_cents=20_000 + n * 150, usual_service_id=services[service],
                        revenue_basis_cents=(basis // count + (i % 9) * 700) if count and basis else 0,
                        revenue_kind=kind,
                        likelihood_score=88 if (key == "overdue_maintenance" and i == 0) else 30 + (n * 7) % 55,
                        points=_points(n, services[service]), change="new" if n % 3 == 0 else "unchanged",
                        reasons=[f"Last visit {days} days ago, usual {service} every 120 days",
                                 "Dormant, but matches none of the enabled patient types" if key is None
                                 else f"Matches {key.replace('_', ' ')}"],
                    )
                )  # fmt: skip
        for i in range(at_risk):
            n += 1
            patient = Patient(
                tenant_id=tenant_id, first_name="Risky", last_name=f"Patient{i:02d}", attributes=dict(MARK)
            )
            s.add(patient)
            await s.flush()
            s.add(
                RunPatient(
                    tenant_id=tenant_id, run_id=run.id, patient_id=patient.id, status="at_risk", primary_type=None,
                    matched_types=[], last_visit_at=finished - timedelta(days=100), days_since_last_visit=100,
                    overdue_ratio=0.9, visit_count=3, total_spend_cents=30_000, usual_service_id=services["Facial"],
                    revenue_basis_cents=0, revenue_kind="new", likelihood_score=40 + i,
                    points=_points(n, services["Facial"]),
                    reasons=["Last visit 100 days ago, due again soon"],
                )
            )  # fmt: skip


UNCLASSIFIED_ROWS = 6


async def _seed_bulk(tenant_id, run: Run, rows: list, services: dict, finished: datetime, unclassified: int) -> None:
    """The same rows without the per-patient flush, for runs with tens of thousands of patients."""
    plan = [(r[0], r[1], r[9], r[8]) for r in rows] + [(None, unclassified, "Facial", "new")]
    n = 0
    async with tenant_session(tenant_id) as s:
        for key, count, service, kind in plan:
            for start in range(0, count, 2000):
                batch = []
                for _ in range(min(2000, count - start)):
                    n += 1
                    batch.append(
                        (
                            n,
                            Patient(
                                tenant_id=tenant_id, first_name=FIRST[n % 12], last_name=LAST[(n // 12 + n) % 12],
                                attributes=dict(MARK),
                            ),
                        )
                    )  # fmt: skip
                s.add_all(p for _, p in batch)
                await s.flush()  # ids are made here
                run_rows = []
                for k, patient in batch:
                    days = 120 + (k * 13) % 500
                    run_rows.append(
                        RunPatient(
                            tenant_id=tenant_id, run_id=run.id, patient_id=patient.id, status="dormant",
                            primary_type=key, matched_types=[key] if key else [],
                            last_visit_at=finished - timedelta(days=days), days_since_last_visit=days,
                            overdue_ratio=round(1.1 + (k % 25) / 10, 2), visit_count=2 + k % 5,
                            total_spend_cents=20_000 + k * 150, usual_service_id=services[service],
                            revenue_basis_cents=20_000 + (k % 9) * 700, revenue_kind=kind,
                            likelihood_score=30 + (k * 7) % 55, points=_points(k, services[service]),
                            change="unchanged", reasons=[f"Last visit {days} days ago"],
                        )
                    )  # fmt: skip
                s.add_all(run_rows)
                await s.flush()


async def _seed_run(
    tenant_id, *, first_run: bool, finished: datetime, services: dict, patients: bool = False, scale: int = 1
) -> Run:
    config = ReactivationSettings().model_dump(mode="json")
    config["types"]["churned_member"]["enabled"] = True
    low = high = 0
    rows = []
    for key, count, basis, service, source in NEW_TYPES:
        count, basis = count * scale, basis * scale
        rate_low, rate_high = _rates(source)
        rows.append(
            (
                key,
                count,
                basis,
                rate_low,
                rate_high,
                source,
                round(basis * rate_low),
                round(basis * rate_high),
                "new",
                service,
            )
        )
        low, high = low + rows[-1][6], high + rows[-1][7]
    key, count, basis, service = RETENTION
    count, basis = count * scale, basis * scale
    rows.append((key, count, basis, 1.0, 1.0, "assumed", basis, basis, "retention", service))
    unclassified = 6 * scale
    dormant = sum(r[1] for r in rows) + unclassified
    summary = {
        "as_of": finished.isoformat(),
        "patients_total": 235 * scale,
        "patients_scored": 221,
        "dormant_count": dormant,
        "at_risk_count": 18,
        "unclassified_dormant": unclassified,
        "new_revenue_low_cents": low,
        "new_revenue_high_cents": high,
        "retention_value_cents": 910_000,
        "first_run": first_run,
        "newly_dormant": 0 if first_run else 65,
        "unchanged_dormant": 0 if first_run else dormant - 65,
        "returned_since_last": 0 if first_run else 32,
        "types_data_available": {
            "lapsed_high_value": True,
            "lapsed_regular": True,
            "churned_member": False,
            "consult_not_converted": True,
            "overdue_maintenance": True,
            "one_and_done": True,
            "unused_balance": True,
        },
    }
    async with tenant_session(tenant_id) as s:
        run = Run(
            tenant_id=tenant_id,
            trigger="manual",
            status="completed",
            settings_version=0,
            settings=config,
            queued_at=finished - timedelta(minutes=2),
            started_at=finished - timedelta(minutes=1),
            finished_at=finished,
            progress_pct=100,
            summary=summary,
            quality=_quality(),
        )
        s.add(run)
        await s.flush()
        for key, count, basis, rl, rh, source, lo, hi, kind, service in rows:
            s.add(
                RunType(
                    tenant_id=tenant_id, run_id=run.id, type_key=key, patient_count=count, basis_total_cents=basis,
                    rate_low=rl, rate_high=rh, rate_source=source, revenue_low_cents=lo, revenue_high_cents=hi,
                    revenue_kind=kind, top_service_id=services[service],
                )
            )  # fmt: skip
    if patients and scale == 1:
        await _seed_patients(tenant_id, run, rows, services, finished, at_risk=summary["at_risk_count"])
    elif patients:
        await _seed_bulk(tenant_id, run, rows, services, finished, unclassified)
    return run


async def seed(args) -> dict:
    tenant = await _tenant(args.tenant_name)
    await _wipe(tenant.id)
    facts: dict = {"tenant_id": str(tenant.id), "scenario": args.scenario}
    if args.scenario == "empty":
        return facts
    if args.scenario == "none":  # patients with no visits: there is data to analyse, but no analysis yet
        async with tenant_session(tenant.id) as s:
            for name in ("Ada", "Ben", "Cy"):
                s.add(Patient(tenant_id=tenant.id, first_name=name, attributes=dict(MARK)))
        return facts
    async with tenant_session(tenant.id) as s:
        services = {}
        for name in ("Filler", "Neurotoxin", "Laser package", "Facial", "Facial package"):
            svc = Service(tenant_id=tenant.id, name=name, attributes=dict(MARK))
            s.add(svc)
            await s.flush()
            services[name] = svc.id
    now = datetime.now(UTC)
    if args.scenario == "large":
        large = await _seed_run(
            tenant.id, first_run=True, finished=now - timedelta(hours=1), services=services, patients=True,
            scale=max(2, args.patients // 186),
        )  # fmt: skip
        facts.update(dormant=large.summary["dormant_count"], total=large.summary["patients_total"])
        return facts
    if args.scenario in ("full", "failed"):
        await _seed_run(tenant.id, first_run=True, finished=now - timedelta(days=9), services=services)
    latest = await _seed_run(
        tenant.id,
        first_run=args.scenario == "first",
        finished=now - timedelta(hours=3, minutes=5),
        services=services,
        patients=True,
    )
    s_ = latest.summary
    facts.update(
        dormant=s_["dormant_count"], total=s_["patients_total"], low=s_["new_revenue_low_cents"],
        high=s_["new_revenue_high_cents"], newly=s_["newly_dormant"], returned=s_["returned_since_last"],
        unclassified=s_["unclassified_dormant"],
    )  # fmt: skip
    if args.scenario == "failed":
        async with tenant_session(tenant.id) as s:
            s.add(
                Run(
                    tenant_id=tenant.id, trigger="manual", status="failed", settings_version=0, settings={},
                    queued_at=now - timedelta(minutes=30), finished_at=now - timedelta(minutes=29),
                    error_code="timed_out",
                )
            )  # fmt: skip
    return facts


async def work(args) -> dict:
    tenant = await _tenant(args.tenant_name)
    async with tenant_session(tenant.id) as s:
        run_id = await s.scalar(select(Run.id).where(Run.status == "queued").order_by(Run.queued_at.desc()))
    if run_id is None:
        sys.exit("no queued run to execute")
    await asyncio.sleep(args.delay)  # lets the page show the queued state before the work starts
    return {"run_id": str(run_id), "outcome": await execute_run(tenant.id, run_id)}


async def cleanup(args) -> dict:
    tenant = await _tenant(args.tenant_name)
    await _wipe(tenant.id)
    return {"cleaned": str(tenant.id)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["seed", "work", "cleanup"])
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--scenario", choices=["full", "first", "failed", "none", "empty", "large"], default="full")
    parser.add_argument("--delay", type=float, default=0.0)
    parser.add_argument("--patients", type=int, default=12_000, help="for the large scenario")
    args = parser.parse_args()

    async def go() -> dict:
        try:
            return await {"seed": seed, "work": work, "cleanup": cleanup}[args.command](args)
        finally:
            await dispose_engines()

    print(json.dumps(asyncio.run(go())))


if __name__ == "__main__":
    main()
