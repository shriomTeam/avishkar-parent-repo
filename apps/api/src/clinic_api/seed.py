"""Dev seed: a demo med spa in lead-magnet trial, loaded from the sample EMR export.

    pnpm db:seed

Goes through the same path a real client does: suggested mapping -> run_import.
Prints the tenant id to use as the X-Tenant-Id header / in the web app.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from clinic_core.database import dispose_engines, system_session, tenant_session
from clinic_core.entitlements import set_feature
from clinic_core.settings import REPO_ROOT
from clinic_db.models.core import ClinicType, Tenant, TenantStatus
from clinic_integrations import run_import, suggest_mapping
from clinic_integrations.sources import CsvSource

SAMPLES = REPO_ROOT / "packages/integrations/samples/medspa"
DEMO_NAME = "Glow Aesthetics (demo)"
FILES = [("patient", "patients.csv"), ("appointment", "appointments.csv"), ("transaction", "transactions.csv")]


async def main() -> None:
    async with system_session() as s:
        existing = await s.scalar(select(Tenant).where(Tenant.name == DEMO_NAME))
        if existing:
            print(f"Demo tenant already exists: {existing.id}")
            return
        now = datetime.now(UTC)
        tenant = Tenant(
            name=DEMO_NAME,
            clinic_type=ClinicType.MEDSPA,
            status=TenantStatus.TRIAL,
            trial_ends_at=now + timedelta(days=30),
            baa_signed_at=now,
            settings={"booking_url": "https://book.example.com/glow"},
        )
        s.add(tenant)
        await s.flush()
        # The two lead magnets: what a prospect gets before buying anything.
        for key in ("reactivation", "blueprints"):
            await set_feature(s, tenant.id, key, expires_at=tenant.trial_ends_at)
        tenant_id = tenant.id

    for entity, filename in FILES:
        source = CsvSource(await asyncio.to_thread(Path(SAMPLES / filename).read_bytes))
        mapping = suggest_mapping(entity, source.headers())
        async with tenant_session(tenant_id) as session:
            result = await run_import(
                session,
                source=source,
                source_system="demo_emr_export",
                entity_type=entity,
                mapping=mapping,
                filename=filename,
                actor_id="seed",
            )
        print(f"{entity:12} {result.stats()}")
        for err in result.errors[:3]:
            print("   ", err)

    await dispose_engines()
    print(f"\nDemo tenant id: {tenant_id}")
    print("Use it as X-Tenant-Id, or paste it into the web app's tenant box.")


if __name__ == "__main__":
    asyncio.run(main())
