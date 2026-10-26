# Always-On Clinic

One platform for med spas, wellness clinics and HRT clinics, sold by component.
It's a Turborepo monorepo built on **Next.js**, **FastAPI**, **PostgreSQL** and
**BullMQ** (Redis).

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how it fits together and why.
- [Voice receptionist setup and migration docs](docs/voice-receptionist/README.md) cover Google login and the imported dashboard.
- [User management and email delivery](docs/USER_MANAGEMENT.md) covers invitations, permissions, reusable templates and production rollout.
- [docs/ADDING_A_FEATURE.md](docs/ADDING_A_FEATURE.md) is the guide for teams building a feature.

---

## 1. Install the tools (once per machine)

| Tool | Version | Install (macOS) | Check |
|---|---|---|---|
| Node.js | 24.x (matches CI) | `brew install node@24` | `node -v` |
| pnpm | 9.x | `npm install -g pnpm@9` | `pnpm -v` |
| uv (Python) | latest | `brew install uv` | `uv --version` |
| Docker Desktop | latest | [docker.com](https://www.docker.com/products/docker-desktop/) | `docker ps` |

If Homebrew does not select Node 24 automatically, add it to your shell path:

```bash
echo 'export PATH="$(brew --prefix node@24)/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
node -v
```

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
test -f .env || cp .env.example .env
```
```bash
pnpm install
```
```bash
uv sync
```

`pnpm install` installs the JavaScript packages. `uv sync` creates `.venv/` at
the repo root with every Python package, including dev tools (pytest, ruff).

After copying the environment example, configure `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET` in the ignored root `.env`. Register
`http://localhost:3000/api/v1/auth/google/callback` with your Google web OAuth
client. See the [voice setup guide](docs/voice-receptionist/README.md).

## 3. Start the database and load demo data

Run all commands below from the repository root, not your home directory.
Start Docker Desktop first (or run `colima start` if you use Colima).

```bash
pnpm db:up
docker compose up -d --wait postgres redis
```

For an existing database volume, ensure the authentication role exists. This
local-only script preserves existing data and is safe to rerun:

```bash
docker compose exec -T postgres psql -U clinic_owner -d clinic < infra/postgres/auth-role.sql
pnpm db:migrate
```
`pnpm db:seed` is optional: it creates the original synthetic-data demo clinic.
Google onboarding creates your own clinic; the seed clinic is not automatically
assigned to your Google account. Existing database volumes also need the new
auth login role; follow the [existing-volume instructions](docs/voice-receptionist/README.md#local-setup).

| Command | What it does |
|---|---|
| `pnpm db:up` | Starts **Postgres 17** (port 5432) and **Redis 7** (port 6379) in Docker. The first start also creates the database login roles the apps use (`infra/postgres/init.sql`). |
| `pnpm db:migrate` | Creates or updates all schemas, tables and the per-clinic security rules. Safe to re-run. |
| `pnpm db:seed` | Creates a demo clinic, **Glow Aesthetics**, and imports a synthetic EMR export (240 patients, 1,120 appointments, 962 transactions). **It prints a tenant id; copy it.** |

## 4. Run the apps and background delivery

### Recommended: one command for all application processes

After the first-time setup above, use this sequence each time you start work:

```bash
# Repository root; Docker must already be running.
pnpm db:up
docker compose up -d --wait postgres redis
pnpm db:migrate
pnpm dev
```

`pnpm dev` starts the frontend, backend and general background worker together.
The worker also dispatches transactional email every ten seconds, so **no separate
email-worker command is needed when using `pnpm dev`**. Databases are started
separately by the commands above. Keep this terminal open.

| Process | URL | Responsibility |
|---|---|---|
| Frontend | [localhost:3000](http://localhost:3000) | Dashboard, Settings and invitations |
| Backend | [localhost:8000/docs](http://localhost:8000/docs) | FastAPI, authentication and request authorization |
| General worker | No URL | Email delivery/retries, SMS sequences, events and scheduled jobs |
| PostgreSQL | `localhost:5432` by default | Application data, invitations and durable email queue |
| Redis | `localhost:6379` | Background job/event coordination |

### Alternative: separate terminals

Run each command from the repository root in its own terminal:

```bash
# Terminal 1: backend
pnpm --filter @clinic/api dev
```

```bash
# Terminal 2: frontend
pnpm --filter @clinic/web dev
```

```bash
# Terminal 3: background worker (includes email, events and sequences)
pnpm --filter @clinic/worker dev
```

If you only need the frontend, backend and invitation email, use this **instead
of** the general worker in Terminal 3:

```bash
# Email-only worker: no patient sequences or SMS; polls every ten seconds.
uv run python -m clinic_engagement.email.worker
```

To process up to 20 due emails once and exit:

```bash
uv run python -m clinic_engagement.email.worker --once
```

Starting only the frontend and backend does **not** start a worker. Locally, with
SendGrid configured and `EMAIL_TASKS_*` left blank, invitation creation, resend and
mailbox verification attempt delivery immediately after saving, within the API request. The request
may take a few seconds while SendGrid responds (the immediate attempt is bounded
to 5 seconds). A worker is still needed to recover interrupted attempts and retry
temporary failures. Keep the chosen worker running while testing invitations. Use either
the general worker or the email-only worker locally; do not start both for this
setup. The general worker may also process existing patient/SMS jobs according to
your configured messaging provider.

### Configure invitations and SendGrid

Set these values in the ignored root `.env` before starting the API and worker:

```dotenv
INVITATIONS_ENABLED=true
EMAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=<your SendGrid API key with Mail Send permission>
EMAIL_FROM_ADDRESS=abhinav.chaudhary@avishkar.app
EMAIL_FROM_NAME=Avishkar AI
EMAIL_REPLY_TO=abhinav.chaudhary@avishkar.app
EMAIL_PAYLOAD_ENCRYPTION_KEY=<generated Fernet key>
INVITATION_TTL_HOURS=72
PUBLIC_APP_ORIGIN=http://localhost:3000
```

Use a sender verified in **your** SendGrid account; the address above is the
project's configured sender. Generate the payload encryption key once:

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Copy the output into `EMAIL_PAYLOAD_ENCRYPTION_KEY`. Keep it private and stable
across API/worker restarts; generating a replacement prevents pending emails from
being decrypted unless the old key is retained through `EMAIL_OLD_PAYLOAD_KEYS`.
Never commit `.env` or put these secrets in `NEXT_PUBLIC_*` variables. Restart
the API and worker after changing configuration. With the default
`INVITATIONS_ENABLED=false`, new invitations are disabled; `EMAIL_PROVIDER=console`
does not send real emails.

To test, open **account menu → Settings → User management → Invite user** and use
an email that is not already a workspace member. The recipient opens the email,
signs in with that email and accepts to join the **existing workspace**.
To restore someone you removed, filter members by **Inactive**, click
**Re-invite <name>**, choose their new role and send a fresh invitation. Access
returns only after the original account accepts; their membership is reused.

| Email delivery status | Meaning / next step |
|---|---|
| `queued` | Saved; immediate delivery has not completed or was deferred. If it stays here, check email configuration and that the recovery worker is running against the same database. |
| `sending` | A worker has claimed the record for processing. |
| `retry` | A temporary failure occurred; the worker retries with backoff. |
| `accepted` | SendGrid accepted the submission (HTTP 202). Check inbox/spam; this does not confirm inbox delivery. |
| `failed` | Delivery could not complete; inspect the worker's safe error/status and SendGrid configuration. |
| `cancelled` | The queued delivery was cancelled, for example after revoking or replacing an invitation. |

Click **Refresh invitations** to reload the displayed status. Invitation status
`pending` is separate: it remains pending until the recipient accepts, even after
SendGrid accepts the email.

### Production delivery is automatic after rollout

Production does not use `pnpm dev`. New emails are committed to the encrypted
PostgreSQL queue, then their delivery IDs are queued immediately in **Google Cloud
Tasks**. Cloud Tasks calls a dedicated private Cloud Run email service using OIDC;
that service sends through SendGrid and retries transient failures. The invitation
request waits only for bounded task creation, not the SendGrid response.

Cloud Scheduler calls a protected recovery endpoint on the **same email service**
every 30 minutes as a safety net: it re-enqueues records
whose task creation failed, or whose dispatch reservation is older than 15 minutes.
It does not poll SendGrid on the normal production path. Apply Terraform and the
new database migration first; Deploy builds the `email` image and updates the
private email service **before** the API. No extra email API key is needed beyond
the existing SendGrid/payload secrets. Queue settings and scoped IAM are managed by
Terraform. See [production rollout](docs/USER_MANAGEMENT.md#production-rollout).

The configured production app origin is
`https://prod-avishkar-web-287171356403.us-east1.run.app` (without a feature path).
Use this for production `PUBLIC_APP_ORIGIN` and register its Google callback at
`/api/v1/auth/google/callback`; keep local links pointed at localhost.

### Stop and verify

Stop each foreground command with `Ctrl+C` (`pnpm dev` stops its child processes).
Stop local PostgreSQL/Redis without deleting their data:

```bash
pnpm db:down
```

Check running services:

```bash
docker compose ps
curl -f http://localhost:8000/health
curl -I http://localhost:3000
```

The worker has no HTTP endpoint; inspect its terminal logs and the Invitations
email delivery status to verify it is processing mail.

## 5. Try it

1. Open http://localhost:3000/login and **Continue with Google**.
2. Complete clinic onboarding. Your owner account gets a 14-day trial of
   **Dormant Revenue Finder**, **Patient Blueprints**, and **Voice Receptionist**.
3. Open **Voice Receptionist** to use the voice dashboard: agents, numbers, call history,
   tools, variables and test studio. Voice actions use sample data and are
   simulated; authentication and clinic identity are real.
4. Reactivation, blueprints and import pages retain their existing URLs and
   APIs. Real data imports still require a signed BAA.

The API verifies session membership and derives staff roles. Authenticated
writes require a session CSRF token and the configured public origin. The
original header-based synthetic-data API demo is available only when explicitly
setting `ALLOW_DEV_AUTH=true` with `APP_ENV=dev`; the web app uses Google sessions.

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

Browser tests use a test-only cookie to give each browser context an independent
synthetic client address. Login limits still apply within that context; scenarios
and repeated suite runs do not share localhost counters or need counter resets.
Production continues to use real client addresses and the unchanged rate limit.

Turborepo caches builds and static checks; database tests run every time. CI
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
| `Cannot connect to the Docker daemon` | Start Docker Desktop, or run `colima start` if using Colima, then run `pnpm db:up` again. |
| Database role missing / auth returns `service_unavailable` | Check the API logs and database connectivity. For an older local volume, follow the existing-volume role instructions linked in step 3, then rerun migrations; do not reset a volume containing data you need. |
| `port is already allocated` / `EADDRINUSE` | Something else is using 5432, 6379, 3000 or 8000. Stop it, or change the port in `docker-compose.yml` / `.env`. |
| Cannot sign in | Configure Google credentials in root `.env`, ensure callback origin matches, and check `/api/v1/health/ready`. |
| Feature page shows 404 | That feature isn't enabled for this clinic (see the Overview page). |
| Invitation email stays `queued` / `retry` | Check SendGrid settings/API logs and start a recovery worker using step 4. New invitations attempt delivery immediately; interrupted/failed attempts need the worker. |
| `no configuration file provided` from Docker Compose | Run the command from the repository root where `docker-compose.yml` lives. |
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
| Voice receptionist | Imported sample dashboard; live voice APIs/runtime remain to build |
| Lead response, reviews, scribe, command center, photos | Stubs, ready for their teams |
| Login / auth | Google sessions and clinic onboarding; production HTTPS acceptance remains |
| User management | Workspace invitations, acceptance, role changes/removal and workspace switching; production email rollout required |

See the [PR validation report](docs/USER_MANAGEMENT_VALIDATION.md) for test coverage, dependency findings and release gates.

Workspace trial expiry is currently paused while billing is not implemented.
See [workspace access policy](docs/WORKSPACE_ACCESS_POLICY.md); run `pnpm db:migrate`
to convert existing automatic trials without changing disabled products or roles.
