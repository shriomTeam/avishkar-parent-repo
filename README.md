# Always-On Clinic

One platform, sold by component, for med spas, wellness and HRT clinics.
Turborepo monorepo: Next.js + FastAPI + Postgres + BullMQ (Redis).

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the decisions and
[docs/ADDING_A_FEATURE.md](docs/ADDING_A_FEATURE.md) to start on a feature.

## Prerequisites
Node 22+, pnpm 9, [uv](https://docs.astral.sh/uv/), Docker.

## First run

```bash
cp .env.example .env
pnpm install && uv sync
pnpm db:up            # Postgres 17 + Redis 7
pnpm db:migrate
pnpm db:seed          # demo med spa from a synthetic EMR export; prints a tenant id
pnpm dev              # web :3000, API :8000 (docs at /docs), worker
```

Open http://localhost:3000 and paste the tenant id. The demo tenant is a
lead-magnet trial with **Dormant Revenue Finder** and **Patient Blueprints** enabled.

## Everyday commands

| | |
|---|---|
| `pnpm turbo run test --filter=@clinic/feature-reactivation` | test one package |
| `pnpm db:revision "message"` | autogenerate a migration from model changes |
| `pnpm api-client:generate` | refresh TS types after changing the API |
| `pnpm boundaries` | check architectural import rules |
| `uv run ruff check . && uv run ruff format .` | Python lint/format |

Python tests need the local database (`pnpm db:up && pnpm db:migrate`).

## Onboarding a clinic's data
In the web app use **Import data**: upload patients, then appointments, then
transactions (CSV or Excel from any EMR/POS). Review the suggested column
mapping and import. The mapping is saved per source system. For a client
database use `clinic_integrations.sources.SqlSource`; EMR API connectors go in
`packages/integrations/src/clinic_integrations/sources/emr/`.

## Status

| Component | State |
|---|---|
| Platform: tenancy/RLS, entitlements, events, audit, import, engagement engine | working, tested |
| Dormant Revenue Finder (`reactivation`) | working end to end (reference feature) |
| Patient Blueprints (`blueprints`) | working, heuristic v1 |
| Lead response, reviews, voice, scribe, command center, photos | stubs, ready for their teams |
| Auth | dev headers only; replace before any real data |
