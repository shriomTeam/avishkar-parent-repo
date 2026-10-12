# Voice receptionist in Always-On Clinic

The implemented Avishkar Voice AI authentication, onboarding and dashboard now live in this monorepo. The original checkout remains intact. Google login and clinic onboarding use PostgreSQL; agents, calls, numbers, tools, variables, recording previews and test calls remain explicitly simulated.

## Code locations

There is no standalone `apps/voice-receptionist` folder. Voice receptionist is a feature inside the existing `apps/web` frontend and `apps/api` backend. Its browser URL is `/voice-receptionist`; Next.js route groups `(platform)` and `(features)` do not appear in that URL.

| Responsibility | Location |
| --- | --- |
| Voice pages | `apps/web/app/(platform)/(features)/voice-receptionist` |
| Voice screens and scoped CSS | `apps/web/components/voice`, `apps/web/styles/voice.css` |
| Sample data/service adapter | `apps/web/lib/voice` |
| Login/onboarding pages | `apps/web/app/(auth)`, `apps/web/components/auth` |
| Backend auth/provider/session policy | `packages/core/src/clinic_core/auth` |
| Tenant onboarding/membership lookup | `packages/core/src/clinic_core/tenancy` |
| Auth and onboarding HTTP routes | `apps/api/src/clinic_api/routers/auth.py`, `apps/api/src/clinic_api/routers/onboarding.py` |
| Identity models and migration | `packages/db/src/clinic_db/models/auth.py`, `packages/db/migrations/versions/20261012_0002_auth.py` |
| Voice backend entry point | `packages/features/voice-receptionist` (control-plane stub; no source voice APIs existed) |
| Source auth tests | `packages/core/tests/auth`, `apps/api/tests/auth` |
| Browser journeys | `apps/web/tests/voice`, `apps/web/playwright.config.ts` |

The source `agent/`, `jobs/`, and `infra/` contained only placeholders. Live audio is future work; create `apps/voice-agent` when implementing it. Background work uses the existing worker. There is one SQLAlchemy Base, one Alembic history, and one pair of uv/pnpm lockfiles.

## Local setup

Install prerequisites first: Node.js with pnpm, Python 3.12+, `uv` (`brew install uv` on macOS), and a running Docker daemon (`colima start` when using Colima).

If port 5432 is already occupied, set `POSTGRES_PORT=5433` in root `.env` and change the host port to 5433 in all four `DATABASE_*_URL` values. Keep the container port at 5432. This lets both PostgreSQL instances run independently.

From the monorepo root:

```sh
pnpm install
uv sync
cp .env.example .env  # only when .env does not already exist
pnpm db:up
pnpm db:migrate
pnpm dev
```

Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in the ignored root `.env`. Source credentials and environment files were not copied. Register `http://localhost:3000/api/v1/auth/google/callback` with the Google web OAuth client and use `localhost` consistently. `PUBLIC_APP_ORIGIN` and `GOOGLE_REDIRECT_URI` must match. `BACKEND_INTERNAL_URL` is server-only; Next loads the root environment and proxies same-origin auth requests.

If Postgres already has an initialized volume from before this migration, initialize the new auth login role **before** migrating:

```sh
docker compose exec -T postgres psql -U clinic_owner -d clinic < infra/postgres/auth-role.sql
pnpm db:migrate
```

This does not reset or delete existing data. The local script sets the example local `clinic_auth` password; production must provision its own restricted auth role/credentials. New volumes get the role from `infra/postgres/init.sql` automatically.

Open `/login`, sign in with Google, and create your clinic (name, clinic type, timezone, optional callback number). Onboarding creates an owner staff link and a 14-day trial of reactivation, blueprints and voice receptionist. It does not mark a BAA signed. Open **Voice Receptionist** in the clinic sidebar to reach `/voice-receptionist`.

Existing source users/workspaces/database data are not imported by this code migration. Existing parent demo clinics are not assigned to Google users by email; clinic access needs an explicit staff-to-user link. A new login creates a new authenticated clinic through onboarding. The original source database remains untouched.

`ALLOW_DEV_AUTH=false` is the default. The API can retain the original synthetic-data header demo with `ALLOW_DEV_AUTH=true` and `APP_ENV=dev`; the web application always requires a Google session. Selected tenant IDs are checked against active staff membership, and supplied staff role/actor headers are ignored for signed-in sessions.

## Contracts and behavior

- Google auth endpoints retain `/api/v1/auth/*`; compatibility onboarding uses `/api/v1/workspaces` and creates canonical `core.tenants`/`core.staff`, not separate workspace tables.
- `/me` remains the platform entitlement/navigation response; `/api/v1/auth/me` is session/account/onboarding information.
- Feature backend endpoints remain `/features/voice_receptionist/*` and use the existing feature entitlement gate. The voice frontend layout also calls `requireFeature`.
- Global auth tables use the restricted `clinic_auth` connection. Verified-user membership lookup and atomic provisioning use narrowly scoped system-session operations. Feature requests then use tenant RLS sessions as before.
- Authenticated platform writes require CSRF and the configured public origin. Server actions forward cookies, CSRF and origin to FastAPI; browser authentication uses same-origin cookies.
- Voice routes retain the original Avishkar sidebar, workspace card, header and responsive shell. The parent sidebar is replaced on these routes; “All clinic products” returns to the platform overview. Source CSS is prefixed with `.voice-scope` to prevent styling other products.
- Sample mutations last across voice navigation until refresh. Reset demo does not reset your real identity or clinic. No real calls, tool requests, recordings or patient records are produced by the sample dashboard.

## Checks

```sh
uv run ruff check .
uv run ruff format --check .
pnpm boundaries
pnpm api-client:generate
pnpm typecheck
pnpm test
pnpm build
```

API auth integration tests and browser tests need a disposable, migrated database with all three runtime roles. Set `TEST_DATABASE_URL` (clinic_app), `TEST_AUTH_DATABASE_URL` (clinic_auth), and `TEST_SYSTEM_DATABASE_URL` (clinic_system), using `postgresql+psycopg://` URLs. Tests insert records; do not point them at a production or source database.

```sh
uv run pytest packages/core/tests/auth apps/api/tests/auth -q
pnpm --filter @clinic/web test:e2e
```

Playwright starts its test-only provider and API on 8001 and Next on 3100. Google Chrome is used locally as in the source suite; CI installs Playwright Chromium. Keep test-only providers out of production. The browser suite verifies simulated-provider sessions and dashboard behavior; real Google consent/token exchange and production HTTPS remain separate acceptance checks. Run build and browser checks sequentially because both use the web app build directory.

## Container backend option

`apps/api/Dockerfile` builds from the repository root. Run the optional `app` profile when you want API/worker containers instead of the local Python processes:

```sh
docker compose --profile app build api
docker compose --profile app run --rm migrate
docker compose --profile app up api worker
```

Run the Next frontend separately with `pnpm --filter @clinic/web dev`. Do not also start `pnpm dev`, which would start another API on port 8000. Database migration is an explicit service, rather than a race between API replicas. Container configuration uses the parent database and Redis services. Docker image execution has not been verified during this local migration.

## Documents

- [Migration plan](VOICE_AI_MIGRATION_PLAN.md)
- [Verification results](VALIDATION.md)
- [Source provenance](SOURCE.md)
- [Original product README](SOURCE_README.md)
- [Original backend guide](BACKEND_SOURCE_README.md)
- [Original frontend guide](FRONTEND_SOURCE_README.md)
- [Google implementation plan](google_sign_in_plan.md)
- [Frontend implementation plan](frontend_plan.md)
- [Original week plan](1_week_plan.md)
- [Architecture blueprint](Open_Source_Retell_AI_Architecture_Blueprint.pdf)

Original guides describe the source folder layout and are retained as historical references. Use this README for current setup. The migration plan separates relocation of existing code from future voice API/runtime implementation.
