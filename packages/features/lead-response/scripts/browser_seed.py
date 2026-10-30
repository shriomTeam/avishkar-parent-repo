"""Browser-test helper for the Lead response settings page. Touches ONLY the disposable TEST_* databases.

    SEED="uv run python packages/features/lead-response/scripts/browser_seed.py"
    $SEED enable     --tenant-name NAME [--scenario standard|saved]
    $SEED bump       --tenant-name NAME
    $SEED front-desk --tenant-name NAME
    $SEED hold       --tenant-name NAME --seconds 4
    $SEED cleanup    --tenant-name NAME

The feature is "available=False" on the platform and no provisioning path switches it on, so a workspace made by the
browser sign-in does not have it. `enable` adds the entitlement row the API checks (`require_feature`), and with
`--scenario saved` also two saved settings versions (version 2 is current). `bump` saves one more version behind the
page's back, so the next save from the page gets a 412. `front-desk` gives the workspace owner a real front-desk
role, so the platform's own role check answers 403. `hold` takes a lock on lead_response.practice_settings for a few
seconds so the settings read waits, which is how the loading skeleton is seen (the read is server to server, so the
browser cannot delay it). It prints one JSON line when the lock is held and releases it in a finally. `cleanup` removes
the settings versions and the entitlement of the workspace; the workspace itself is created by the browser sign-in and
is left alone, like the other browser journeys.

Safety: it refuses to start unless TEST_DATABASE_URL and TEST_SYSTEM_DATABASE_URL are set, and refuses when either
points at the same database as the configured DATABASE_* URLs (CI, whose database is disposable, sets CI=true and may
share a name). The DATABASE_* settings are then replaced with the TEST_* URLs for this process, so nothing here can
reach the development database. Prints one JSON line of facts for the test.
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

from sqlalchemy import delete, func, select, text, update  # noqa: E402

from clinic_core.database import dispose_engines, system_session, tenant_session  # noqa: E402
from clinic_core.entitlements import set_feature  # noqa: E402
from clinic_db.models.core import Staff, Tenant, TenantFeature  # noqa: E402
from clinic_db.models.lead_response import PracticeSettings  # noqa: E402
from clinic_lead_response.settings_model import LeadResponseSettings  # noqa: E402
from clinic_lead_response.settings_store import columns_from_settings  # noqa: E402

FEATURE = "lead_response"
SEEDER = "browser-seed"  # the staff id stored on the versions this script writes


async def _tenant(name: str) -> Tenant:
    async with system_session() as s:
        tenant = (await s.scalars(select(Tenant).where(Tenant.name == name).order_by(Tenant.created_at.desc()))).first()
    if tenant is None:
        sys.exit(f"no workspace named {name!r} in the test database")
    return tenant


async def _add_version(tenant_id, settings: LeadResponseSettings) -> int:
    async with tenant_session(tenant_id) as s:
        current = await s.scalar(select(func.max(PracticeSettings.version))) or 0
        s.add(
            PracticeSettings(
                tenant_id=tenant_id, version=current + 1, created_by=SEEDER, **columns_from_settings(settings)
            )
        )
        return current + 1


def _saved_settings() -> list[LeadResponseSettings]:
    """Two versions: the second is current and differs from the standard settings in every field the page shows."""
    weekdays = {d: [{"start": "09:00", "end": "17:00"}] for d in ("mon", "tue", "wed", "thu")}
    first = LeadResponseSettings(holding_minutes=10, sla_minutes=45)
    second = LeadResponseSettings(
        ack_text="Thanks for texting Glow. We have your message and will reply shortly.",
        holding_minutes=20,
        sla_minutes=60,
        escalation_role="owner",
        business_hours={**weekdays, "fri": [{"start": "08:00", "end": "12:00"}, {"start": "13:00", "end": "16:00"}]},
        quiet_hours={"start": "21:00", "end": "08:00"},
    )
    return [first, second]


async def enable(args) -> dict:
    tenant = await _tenant(args.tenant_name)
    async with system_session() as s:
        await set_feature(s, tenant.id, FEATURE)
    version = 0
    if args.scenario == "saved":
        for settings in _saved_settings():
            version = await _add_version(tenant.id, settings)
    return {"tenant": str(tenant.id), "version": version, "timezone": tenant.timezone}


async def bump(args) -> dict:
    """Someone else saves: one more version with the holding timer one minute longer."""
    tenant = await _tenant(args.tenant_name)
    async with tenant_session(tenant.id) as s:
        row = (await s.scalars(select(PracticeSettings).order_by(PracticeSettings.version.desc()).limit(1))).first()
    current = LeadResponseSettings.model_validate(
        {} if row is None else {"holding_minutes": row.holding_minutes, "sla_minutes": row.sla_minutes}
    )
    current.holding_minutes += 1
    current.sla_minutes = max(current.sla_minutes, current.holding_minutes + 1)
    return {"version": await _add_version(tenant.id, current)}


async def set_role(args) -> dict:
    """Assign a real role in this guarded disposable workspace, so the platform's own check answers."""
    tenant = await _tenant(args.tenant_name)
    async with system_session() as s:
        await s.execute(
            update(Staff).where(Staff.tenant_id == tenant.id, Staff.role == "owner").values(role="front_desk")
        )
    return {"role": "front_desk"}


async def hold(args) -> None:
    """Hold an exclusive lock on the settings table so any read of it waits. Released when the time is up or the
    process ends (a dropped connection releases it too)."""
    async with system_session() as s:
        try:
            await s.execute(text("SET LOCAL lock_timeout = '3s'"))  # never wait forever to get the lock
            await s.execute(text("LOCK TABLE lead_response.practice_settings IN ACCESS EXCLUSIVE MODE"))
            print(json.dumps({"locked": True, "seconds": args.seconds}), flush=True)
            await asyncio.sleep(args.seconds)
        finally:
            await s.rollback()  # ends the transaction and so releases the lock
    print(json.dumps({"released": True}), flush=True)


async def cleanup(args) -> dict:
    tenant = await _tenant(args.tenant_name)
    async with tenant_session(tenant.id) as s:
        await s.execute(delete(PracticeSettings))
    async with system_session() as s:
        await s.execute(
            delete(TenantFeature).where(TenantFeature.tenant_id == tenant.id, TenantFeature.feature_key == FEATURE)
        )
    return {"cleaned": str(tenant.id)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["enable", "bump", "front-desk", "hold", "cleanup"])
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--scenario", choices=["standard", "saved"], default="standard")
    parser.add_argument("--seconds", type=float, default=4.0, help="for hold")
    args = parser.parse_args()
    commands = {"enable": enable, "bump": bump, "front-desk": set_role, "hold": hold, "cleanup": cleanup}

    async def go():
        try:
            return await commands[args.command](args)
        finally:
            await dispose_engines()

    result = asyncio.run(go())
    if result is not None:
        print(json.dumps(result))


if __name__ == "__main__":
    main()
