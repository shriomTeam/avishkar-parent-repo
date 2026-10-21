"""Dev only. Run one queued reactivation run for a tenant directly, without the worker (default: the demo).

    uv run python packages/features/reactivation/scripts/run_one.py
    uv run python packages/features/reactivation/scripts/run_one.py --tenant-id <uuid>

Uses the tenant's saved settings (or the defaults). If no run is queued it requests a manual one first, which
also writes a reactivation.run.requested event; a running worker may then pick the run up before this script
does, and the script reports that. Writes a real run to the database. Prints counts and ids only, never names.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from clinic_core.database import dispose_engines, system_session, tenant_session
from clinic_db.models.core import Tenant
from clinic_db.models.reactivation import Run
from clinic_reactivation.runs import execute_run, request_manual

DEMO_NAME = "Glow Aesthetics (demo)"


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

    async with tenant_session(tenant.id) as s:
        run_id = await s.scalar(select(Run.id).where(Run.status == "queued"))
        if run_id is None:
            request = await request_manual(s, actor_id="dev-script", idempotency_key=None, now=datetime.now(UTC))
            run_id = request.run.id
            print(f"no queued run: requested {run_id} ({request.settings_source} settings)")
        else:
            print(f"running the queued run {run_id}")

    outcome = await execute_run(tenant.id, run_id)
    async with tenant_session(tenant.id) as s:
        row = await s.get(Run, run_id)
    print(f"outcome: {outcome}  status: {row.status}  error_code: {row.error_code}  error_detail: {row.error_detail}")
    if outcome in ("skipped", "busy"):
        print("not executed here: the run was already taken, or another run is running (see the status above)")
    if row.started_at and row.finished_at:
        print(f"took {(row.finished_at - row.started_at).total_seconds():.1f}s")
    if row.summary is not None:
        print("summary:\n" + json.dumps(row.summary, indent=2, sort_keys=True))
        print("quality:\n" + json.dumps(row.quality, indent=2, sort_keys=True))
    return 0 if row.status == "completed" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", type=uuid.UUID, help="default: the demo tenant")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    async def go() -> int:
        try:
            return await run(args)
        finally:
            await dispose_engines()

    sys.exit(asyncio.run(go()))


if __name__ == "__main__":
    main()
