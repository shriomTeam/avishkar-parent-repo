# Always-On Clinic

One platform for med spas, wellness clinics and HRT clinics, sold by component.
It's a Turborepo monorepo built on **Next.js**, **FastAPI**, **PostgreSQL** and
**BullMQ** (Redis).

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how it fits together and why.
- [docs/ADDING_A_FEATURE.md](docs/ADDING_A_FEATURE.md) is the guide for teams building a feature.

---

## 1. Install the tools (once per machine)

| Tool | Version | Install (macOS) | Check |
|---|---|---|---|
| Node.js | 22 or newer | `brew install node` | `node -v` |
| pnpm | 9.x | `npm install -g pnpm@9` | `pnpm -v` |
| uv (Python) | latest | `brew install uv` | `uv --version` |
| Docker Desktop | latest | [docker.com](https://www.docker.com/products/docker-desktop/) | `docker ps` |

You don't need to install Python yourself: `uv` downloads Python 3.12
(pinned in `.python-version`) the first time you run `uv sync`. Docker Desktop
must be **running** before you start the database.

## 2. Get the code and install dependencies

```bash
git clone https://github.com/shriomTeam/avishkar-parent-repo.git
```
```bash
cd avishkar-parent-repo
```
```bash
cp .env.example .env
```
```bash
pnpm install
```
```bash
uv sync
```

`pnpm install` installs the JavaScript packages. `uv sync` creates `.venv/` at
the repo root with every Python package, including dev tools (pytest, ruff).

## 3. Start the database and load demo data

```bash
pnpm db:up
```
```bash
pnpm db:migrate
```
```bash
pnpm db:seed
```

| Command | What it does |
|---|---|
| `pnpm db:up` | Starts **Postgres 17** (port 5432) and **Redis 7** (port 6379) in Docker. The first start also creates the database login roles the apps use (`infra/postgres/init.sql`). |
| `pnpm db:migrate` | Creates or updates all schemas, tables and the per-clinic security rules. Safe to re-run. |
| `pnpm db:seed` | Creates a demo clinic, **Glow Aesthetics**, and imports a synthetic EMR export (240 patients, 1,120 appointments, 962 transactions). **It prints a tenant id; copy it.** |

## 4. Run the apps

All three at once:

```bash
pnpm dev
```

| App | URL | What it is |
|---|---|---|
| Web | http://localhost:3000 | Next.js dashboard |
| API | http://localhost:8000 | FastAPI. Interactive docs are at http://localhost:8000/docs |
| Worker | (no URL; it logs to the terminal) | Sends SMS/email, delivers events between features, runs scheduled jobs |

To run one at a time, use separate terminals:

```bash
pnpm --filter @clinic/api dev
```
```bash
pnpm --filter @clinic/web dev
```
```bash
pnpm --filter @clinic/worker dev
```

Stop with `Ctrl+C`. Stop the database with `pnpm db:down`.

## 5. Try it

1. Open http://localhost:3000 and paste the tenant id from `pnpm db:seed`.
2. **Overview** lists every product component. The demo is a trial, so only
   **Dormant Revenue Finder** and **Patient Blueprints** are active.
3. **Reactivation** shows dormant patients and their past spend. Click
   **Create campaign**, then **Launch**.
   - In dev, messages are not really sent. The worker prints them as `[sms -> +1...]`.
   - Messages only go out between 8am and 9pm clinic time (America/New_York for the demo).
     Outside those hours they are scheduled for the next 8am.
4. **Patient Blueprints** shows the top three buying profiles.
5. **Import data** loads your own CSV or Excel file. Try the files in
   `packages/integrations/samples/medspa/` (import patients first, then
   appointments, then transactions).

To call the API directly, send the tenant id as a header. This is dev-only
auth; real login is not built yet.

```bash
curl -H "X-Tenant-Id: <tenant-id>" http://localhost:8000/features/reactivation/preview
```

To create another clinic with chosen features, use `POST /admin/tenants` at
http://localhost:8000/docs (only available in dev).

## 6. Tests and checks

The database must be up and migrated (steps 3 and 4).

| Command | What it does |
|---|---|
| `pnpm test` | All Python tests (API, import, features) |
| `pnpm lint` | ruff on every Python package |
| `pnpm typecheck` | TypeScript checks for web, ui, api-client |
| `pnpm build` | Production build of the web app |
| `pnpm boundaries` | Architecture rules (features may not import each other, etc.) |
| `pnpm turbo run test lint --filter=@clinic/feature-reactivation` | Only one package |
| `uv run ruff format .` | Auto-format Python code |

Turborepo caches results, so unchanged packages are skipped on re-runs. CI
(`.github/workflows/ci.yml`) runs all of the above on every pull request.

## 7. Working on the database

| Command | When to use it |
|---|---|
| `pnpm db:revision "add reviews tables"` | After changing models in `packages/db/src/clinic_db/models/`. Generates a migration; review it before committing. |
| `pnpm db:migrate` | Apply new migrations (also after pulling someone else's). |
| `pnpm --filter @clinic/db check-heads` | Make sure two branches didn't both add a migration at the same point. |
| `pnpm api-client:generate` | After changing any API endpoint. Regenerates the TypeScript types the web app uses. |

To reset everything (deletes all local data):

```bash
docker compose down -v
```

Then run step 3 again.

## Troubleshooting

| Problem | Fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop, then run `pnpm db:up` again. |
| `role "clinic_app" does not exist` | Your database volume predates the role setup. Reset with `docker compose down -v`, then run step 3. |
| `port is already allocated` / `EADDRINUSE` | Something else is using 5432, 6379, 3000 or 8000. Stop it, or change the port in `docker-compose.yml` / `.env`. |
| Web shows "Pick a tenant" | Paste the id printed by `pnpm db:seed`. Running the seed again prints the existing id. |
| Feature page shows 404 | That feature isn't enabled for this clinic (see the Overview page). |
| `uv: command not found` | `brew install uv`, then open a new terminal. |

## Repository layout

```
apps/web                    Next.js dashboard
apps/api                    FastAPI backend (+ seed script)
apps/worker                 BullMQ background worker
packages/db                 All database models + Alembic migrations
packages/core               Tenancy, feature contract, entitlements, events, audit
packages/integrations       Client data import (CSV, Excel, SQL; EMR connectors go here)
packages/engagement         Shared SMS/email sequence engine + consent rules
packages/features/*         One package per sellable component
packages/ui                 Shared React components
packages/api-client         Generated TypeScript API types
```

## Status

| Component | State |
|---|---|
| Platform: tenancy/RLS, entitlements, events, audit, import, engagement engine | Working, tested |
| Dormant Revenue Finder (`reactivation`) | Working end to end (the reference feature) |
| Patient Blueprints (`blueprints`) | Working, simple heuristic v1 |
| Lead response, reviews, voice receptionist, scribe, command center, photos | Stubs, ready for their teams |
| Login / auth | Dev headers only; must be replaced before real patient data |
