"""Dev only. Compare analyse() with the old rules.find_lapsed_patients on one tenant (default: the demo).

    uv run python packages/features/reactivation/scripts/shadow_check.py
    uv run python packages/features/reactivation/scripts/shadow_check.py --tenant-id <uuid> --lapsed-days 120
    uv run python packages/features/reactivation/scripts/shadow_check.py --settings saved

Read-only. Needs the local database (pnpm db:up). Prints ids and rule codes only, never names. Every patient
in one set and not the other gets the rule that explains it (docs/data-contract.md, appendix B); a difference
with no explanation is flagged and the script exits with status 1.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import select

from clinic_core.database import dispose_engines, system_session, tenant_session
from clinic_db.models.core import Service, Tenant
from clinic_db.models.reactivation import Settings
from clinic_reactivation import service
from clinic_reactivation.analysis.engine import analyse
from clinic_reactivation.analysis.exclusions import exclusion_reason
from clinic_reactivation.analysis.facts import PatientFacts, load_facts
from clinic_reactivation.analysis.settings import ReactivationSettings
from clinic_reactivation.analysis.types import Classification, classify
from clinic_reactivation.rules import LapsedPatient, find_lapsed_patients
from clinic_reactivation.runs import load_measured_rates

DEMO_NAME = "Glow Aesthetics (demo)"
UNEXPLAINED = "UNEXPLAINED"


def explain(
    f: PatientFacts,
    c: Classification,
    old: LapsedPatient | None,
    lapsed_days: int,
    settings: ReactivationSettings,
    now: datetime,
) -> list[str]:
    """The rules that account for this patient being in only one of the two sets."""
    why: list[str] = []
    excluded = exclusion_reason(f) or ("no_completed_visits" if f.visit_count < 1 else None)
    if excluded:
        why.append(f"engine excludes the patient before scoring: {excluded}")
    days = c.days_since_last_visit
    if days is None:
        return why or [UNEXPLAINED]
    min_days = settings.dormant.min_days_since_visit
    # the old rule counts 24-hour periods on UTC instants; the engine counts clinic-local calendar days
    last_instant = f.visit_starts[-1] if f.visit_starts else None
    old_style_days = (now - last_instant).days if last_instant is not None else None

    if old is None:  # dormant in the engine, not lapsed in the old rule
        if c.status != "dormant":
            return why or [UNEXPLAINED]
        by_interval, by_min = days > c.interval_days, days > min_days
        if by_interval and c.interval_days < lapsed_days:
            why.append(
                f"interval of {c.interval_days} days ({c.interval_source}) is shorter than the old {lapsed_days}"
            )
        if by_min and min_days < lapsed_days:
            why.append(f"min_days_since_visit {min_days} is shorter than the old {lapsed_days}")
        if not (by_interval or by_min) and c.matched_types:
            why.append("a type's own entry rule makes them dormant (D11): " + ", ".join(c.matched_types))
        if days > lapsed_days >= (old_style_days if old_style_days is not None else lapsed_days):
            why.append("local calendar days vs the old 24-hour periods")
    else:  # lapsed in the old rule, not dormant in the engine
        if f.has_future_booking:
            why.append("future booking")
        if c.status != "dormant" and c.interval_days > lapsed_days and days <= c.interval_days:
            why.append(f"interval of {c.interval_days} days ({c.interval_source}) is longer than the old {lapsed_days}")
        if c.status != "dormant" and min_days > lapsed_days and days <= min_days and days <= c.interval_days:
            why.append(f"min_days_since_visit {min_days} is longer than the old {lapsed_days}")
        if old_style_days is not None and old_style_days > lapsed_days >= days:
            why.append("local calendar days vs the old 24-hour periods")
    return why or [UNEXPLAINED]


async def run(args: argparse.Namespace) -> int:
    async with system_session() as s:
        stmt = (
            select(Tenant).where(Tenant.id == args.tenant_id)
            if args.tenant_id
            else select(Tenant).where(Tenant.name == DEMO_NAME)
        )
        tenant = (await s.scalars(stmt)).first()
    if tenant is None:
        print("tenant not found (run pnpm db:seed for the demo tenant)")
        return 2
    now = datetime.now(UTC)

    async with tenant_session(tenant.id) as s:
        settings = ReactivationSettings()
        if args.settings == "saved":
            row = await s.scalar(select(Settings))
            settings = ReactivationSettings.model_validate(row.config) if row else settings
        lapsed_days = args.lapsed_days or await service.default_lapsed_days(s)
        facts = await load_facts(s, now, tenant.timezone, cohort_min=settings.limits.spend_cohort_minimum)
        old = {p.patient_id: p for p in await find_lapsed_patients(s, lapsed_days=lapsed_days, now=now)}
        measured = await load_measured_rates(s, now, settings.revenue.attribution_window_days)
        names = {sv.id: sv.name for sv in (await s.scalars(select(Service))).all()}

    result = analyse(facts, settings, measured, {}, None, now, tenant.timezone, service_names=names)
    engine_dormant = {r.patient_id for r in result.patients if r.status == "dormant"}
    by_id = {f.patient_id: f for f in facts}

    only_engine = sorted(engine_dormant - old.keys(), key=lambda u: u.int)
    only_old = sorted(old.keys() - engine_dormant, key=lambda u: u.int)
    print(f"tenant {tenant.id}  ({tenant.clinic_type}, {tenant.timezone})  as of {now.isoformat(timespec='seconds')}")
    print(f"old rule: lapsed for {lapsed_days}+ days -> {len(old)} patients")
    print(f"engine:   dormant -> {len(engine_dormant)} patients  (at risk {result.summary['at_risk_count']}, "
          f"excluded {result.summary['patients_excluded']}, errored {result.summary['patients_errored']})")  # fmt: skip
    print(f"in both: {len(engine_dormant & old.keys())}   only engine: {len(only_engine)}   only old: {len(only_old)}")

    tally: Counter[str] = Counter()
    unexplained = 0
    for label, ids in (("only engine", only_engine), ("only old", only_old)):
        for pid in ids:
            f = by_id[pid]
            c = classify(f, settings, now, tenant.timezone)
            why = explain(f, c, old.get(pid), lapsed_days, settings, now)
            tally.update(why)
            unexplained += UNEXPLAINED in why
            print(f"  {label:11} {pid}  days={c.days_since_last_visit} interval={c.interval_days}  -> {'; '.join(why)}")
    if tally:
        print("explanations:")
        for reason, n in tally.most_common():
            print(f"  {n:4}  {reason}")
    print("UNEXPLAINED differences: " + (str(unexplained) if unexplained else "none"))
    return 1 if unexplained else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=uuid.UUID, help="default: the demo tenant")
    parser.add_argument("--lapsed-days", type=int, help="the old rule's threshold; default is the clinic type's")
    parser.add_argument("--settings", choices=("default", "saved"), default="default")
    args = parser.parse_args()

    async def go() -> int:
        try:
            return await run(args)
        finally:
            await dispose_engines()

    sys.exit(asyncio.run(go()))


if __name__ == "__main__":
    main()
