# Always-On Clinic

One multi-tenant platform sold as components (features), built as a **modular monolith**: one API, one worker, one web app, one Postgres. Do not split features into services; extraction later is a new `apps/<name>` that mounts the same feature package.

Read before building: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (why it is shaped this way), [docs/ADDING_A_FEATURE.md](docs/ADDING_A_FEATURE.md) (feature walkthrough, `reactivation` is the reference), [README.md](README.md) (local setup and commands).

## Layout

```text
apps/
  web/                         one Next.js app
    app/
      (auth)/                  login and clinic onboarding
      (fullscreen)/voice-receptionist/  voice routes with their own shell
      (platform)/              authenticated platform routes
        layout.tsx             shared auth provider and platform shell
        page.tsx               clinic product overview
        settings/              shared workspace editing, members and audit
                               (accessed through the bottom profile menu)
        import/                patient data import
        (features)/
          blueprints/          existing patient blueprint pages
          reactivation/        thin routes to the feature's pages; campaigns/ still lives here
    components/
      auth/                    onboarding and sign-out controls
      platform-frame.tsx       generic platform shell (no feature path checks)
      platform-navigation.tsx  platform navigation and workspace header
    lib/
      auth/                    compatibility exports of shared core auth
    public/brand/               platform branding assets
    tests/auth/                 platform-only authentication journeys
    playwright.config.ts       isolated browser-test API and frontend
  api/                         one FastAPI app; mounts installed features
    src/clinic_api/routers/
      auth.py                  /api/v1/auth/* Google login and sessions
      onboarding.py            /api/v1/workspaces clinic onboarding
      invitations.py           scoped invitations, acceptance and member management
    tests/auth/                auth, tenant and entitlement integration tests
    tests/browser_server.py    test-only simulated Google provider
    Dockerfile                 optional API/worker container image
  worker/                      general worker plus private Cloud Tasks HTTP handlers
    email.Dockerfile           private transactional-email sender image
packages/
  db/                          all SQLAlchemy tables and one Alembic stream
    src/clinic_db/models/
      auth.py                  global identities, OAuth transactions, sessions
      core.py                  canonical tenants and staff-to-user links
    migrations/versions/       existing schema plus shared auth migration
  core/                        RLS, feature contract, entitlements, events, audit
    web/                       shared frontend auth, sessions and API access
    src/clinic_core/
      auth/                    Google provider, sessions, CSRF and repositories
      tenancy/                 verified memberships and clinic provisioning
    tests/auth/                shared auth unit tests
  integrations/                client data import
  engagement/                  shared SMS and email engine
    src/clinic_engagement/email/ encrypted mail, tasks.py dispatch, task_app.py private handler, template/ factories
  features/
    reactivation/
      src/                     reactivation backend (analysis engine, runs, CSV import)
      web/                     Dormant patients pages, components, unit and browser tests
    blueprints/src/            blueprint backend
    voice-receptionist/
      src/                     voice backend entry point (control-plane stub)
      tests/                   feature backend/entitlement tests
      web/
        pages/                 screen implementations and feature layout
        components/            voice shell and controls
        lib/                   types, state and service adapters
        styles/                voice-specific CSS
        tests/                 voice browser journeys
    lead-response/src/         lead-response backend
    ...
  ui/                          shared React components
  api-client/                  generated TypeScript API types and shared client
  tsconfig/                    shared TS configs
docs/
  voice-receptionist/          current setup, migration plan, validation,
                               provenance and archived source documents
infra/
  postgres/
    init.sql                   fresh-volume development role initialization
    auth-role.sql              auth login role for existing development volumes
  terraform/                   production GCP
.github/workflows/             ci.yml, terraform.yml, migrate.yml
```

This tree describes the implemented `migration/voice-ai` layout. There is no standalone `apps/voice-receptionist`, `backend/` or `frontend/` app. Voice UI is served at `/voice-receptionist` by `apps/web`; route groups `(fullscreen)`, `(platform)` and `(features)` do not appear in URLs. Its original branded sidebar and header replace the platform shell on voice routes; “All clinic products” returns to the platform.

Feature backend code belongs in its package's `src/`. New features must start in `packages/features/<name>/web/`, with thin one-line route files in `apps/web` importing their pages. Voice and reactivation follow this convention now (reactivation's campaigns page and its server actions still live in `apps/web`). Existing blueprints pages remain in `apps/web/app/(platform)/(features)/` until their team moves them.

Styling is Tailwind (v4, CSS-first). The platform, the voice screens and the shared sign-in and session screens all use it; only `packages/ui/styles/auth.css` (login and onboarding) and the reactivation feature's `reactivation.css` are still plain CSS. Brand tokens (`bg-brand`, `text-ink`, `border-line`, the `app:` / `max-app:` breakpoint at 700 px, the `focus-ring` utility) live in `apps/web/app/globals.css`, which also scans `packages/ui/src` and all of `packages/features` for classes. Reusable building blocks (Button variants, Input, NativeSelect, Textarea, Panel, PageHeading, Tabs, StatCard, DataTable, Badge-style `StatusBadge`, EmptyState, and so on) live in `packages/ui/src` and are exported from `@clinic/ui`. Build new UI from them, and add a new block to `@clinic/ui` when two screens need the same thing. Components do not merge conflicting utilities, so never override a utility a component already sets with another class: use its props (for example `Button size="icon"`, `Input inline`, `H3 flush`). The voice workspace wrapper (`data-testid="voice-app"`, set in `web/pages/layout.tsx`) provides the base font (15 px, line height 1.5) and the 90% zoom on wide screens, so a voice component can rely on them. Prefer test ids and roles over class names in browser tests. Because Tailwind scans every file under `packages/features`, a plain class name that equals a Tailwind utility (`inline`, `grow`, `block`...) will be generated as that utility: do not use such names as hooks.

Shared browser/server auth helpers and API access live in `packages/core/web`, exported through `@clinic/core/web/*`. Feature code must never import `apps/web` or its `@/` alias. Python and frontend boundaries are checked by `pnpm boundaries`. Browser tests are discovered from installed feature workspace manifests (`clinic.webTests`), so deleting a feature removes its tests automatically.

To verify voice removal, run `python scripts/check_voice_removal.py` with all DATABASE_* and TEST_* URLs pointing to a disposable migrated database. It creates an isolated copy, removes the voice package/routes and explicit npm/Python/import-linter registrations, refreshes lockfiles and runs build, tests, boundaries, typechecks and platform auth browser tests. The same applies to any feature: platform code and the platform's test servers must never import a feature. Where a feature's test helper is useful (`apps/api/tests/browser_server.py` uses voice's scripted model), import it only if the feature is installed, and re-raise any other import error. Shared migrations and database data remain intact.

## Voice AI migration

Read [docs/voice-receptionist/README.md](docs/voice-receptionist/README.md) for current setup and paths, [the migration plan](docs/voice-receptionist/VOICE_AI_MIGRATION_PLAN.md) for architecture and future phases, and [validation](docs/voice-receptionist/VALIDATION.md) for checks and limits. Archived source guides retain the old repository paths; do not use their commands for this monorepo.

- Google OAuth, opaque database sessions, CSRF and clinic onboarding are implemented in the shared API/core/DB layers. Source workspace records map to canonical `core.tenants` and `core.staff`; supplied tenant IDs must be checked against verified membership.
- **Inbound call agents** live inside the existing voice screens (no separate page): Voice agents, Test studio, Call history and Overview read real data through `VoiceDataProvider` (`web/lib/voice/provider.tsx`), while Settings still uses the in-memory demo provider and shows a "Demo section" note. Tools, Variables, the Knowledge base and Phone numbers are real too. An agent is a prompt plus the fields to capture; staff test it by calling from the browser. Backend in `clinic_voice_receptionist/inbound/` (REST in `router.py`; call engine in `live/`), tables in `clinic_db/models/voice.py`, browser client in `web/lib/inbound/` (`api.ts`, `draft.ts`, `audio.ts`, `call-client.ts`). There is no agent versioning: each call stores a snapshot of the agent it used.
  - Call flow: `POST /agents/{id}/test-call` snapshots the agent into `voice.calls` and returns a one-time ticket; the browser opens the WebSocket `/features/voice_receptionist/inbound/live?ticket=...` directly on the API origin (`NEXT_PUBLIC_API_URL`), sending 16 kHz PCM16 and receiving 24 kHz PCM16. Tickets last 60 s, work once, and name the tenant. The WebSocket lives in `Feature.websocket_router`, which the API mounts without the HTTP auth dependencies.
  - `CallSession` talks only to a `Transport` (browser WebSocket now, Twilio Media Streams later) and a `ModelConnector` (`gemini.py`, Vertex AI). Each call saves transcript turns, raw model events (no audio, no resumption handle) and captured values (`call_field_values`, validated by `live/fields.py`). Audio is stored only when the agent has **Record the call** on (off by default; see Recordings below). Recordings and transcripts are PHI, so never log them.
  - **Recordings** (`inbound/live/audio.py`, `storage.py`): an agent with `save_recording` keeps the call audio in memory (`CallAudio`, stereo 16 kHz WAV, caller left, agent right, laid out on the call clock; interruptions cut agent audio that had not played) and `CallSession._save_recording` uploads it when the call ends, retrying once. The call row records `recording_object` and `recording_status` (`saved`, `failed`, or null when not recorded). `GET /inbound/calls/{id}/recording` finds the file from that row, checks it sits in the caller's `voice-recordings/<tenant_id>/` folder, and audits `voice.recording.played`. The browser fetches it only when someone presses Play (`recording-player.tsx`), with the session headers, so opening a call downloads nothing. A recording agent refuses to start a call when no bucket is configured. Memory is about 2 MB per minute per call, so a long call holds tens of MB until it ends. A server restart mid-call loses that call's audio. Retention and deletion rules are not set yet.
  - **Variables** (`clinic_voice_receptionist/variables/`, table `voice.variables`): fixed text a clinic defines once (its hours, address) and writes in any agent's prompt or first message as `{{name}}`. They are clinic-wide, not per agent, and only the value can change (the name is what prompts refer to). Built-in variables (`agent_name`, `clinic_name`, `caller_number`, `current_date`, `current_time`) are filled in by the platform and cannot be redefined. Saving an agent with an unknown `{{name}}` is refused with a 422, a variable an agent still uses cannot be deleted (409), and `POST /agents/{id}/test-call` fills every variable in once, in one pass, and stores the finished prompt in the call snapshot while the agent keeps its template. Details captured during a call are not variables: they only exist after the caller has spoken.
  - **Tools** (`clinic_voice_receptionist/tools/`, tables `voice.tools`, `agent_tools`, `tool_executions`): an agent's attached, enabled tools become extra Gemini function declarations in the same Live session; `CallSession._run_tool` runs them through `ToolRunner` and the model waits (Vertex Live has no non-blocking tools), so tools are capped at 10 s. Two kinds: internal (`builtin.py`: a catalog a clinic adds from, via `POST /tools/internal` or the Add tool dialog; today `create_lead`, which writes `core.leads`, links `voice.calls.lead_id` and emits `lead.created`, and `update_lead`, which only changes the lead already made in that call and never creates one) and external, custom HTTPS tools (`http_tool.py`). Nothing is added to a clinic automatically; creating an agent from a starter adds `create_lead` if the clinic lacks it. Internal tools can be removed and re-added.
    - Custom tools run from our servers, so `netguard.py` allows only public HTTPS on port 443, resolves the name and refuses any non-public answer, then connects to that exact IP with SNI set to the real host (defeats DNS rebinding); no redirects, 64 KB response cap, GET retried once, POST never. Auth header values are Fernet-encrypted (`VOICE_SECRETS_KEY`, required outside dev/test) and never returned or copied into call snapshots; the runner reads the tool's current settings at run time, so disabling or deleting a tool takes effect mid-call.
    - Internal tool schemas live in code and, unless a clinic edited the description (`description_customized`), so does the wording; `refresh_builtins` applies code updates to rows a clinic already has. A clinic can switch an internal tool on or off and edit its description, but not its name or arguments (they map to `core.leads` columns). Tool descriptions steer the model: `create_lead` says plainly that `save_caller_details` does not notify the team, because without that Gemini treated the job as done. Re-check wording against the real model after changing it.
    - `VOICE_TOOL_ALLOW_PRIVATE_HOSTS` lets tools call localhost for tests and local demos. It must never be set in production. Before deploying the API, provision `VOICE_SECRETS_KEY` in Secret Manager (Terraform) and give the service account `roles/aiplatform.user`.
  - Model: `VOICE_MODEL` (default `gemini-live-2.5-flash-native-audio`, checked against Vertex `us-central1`). Needs `aiplatform.googleapis.com` and `roles/aiplatform.user`. Before production, deploy the WebSocket as its own Cloud Run service, load-test it, and request Live API quota.
  - Tests: Python tests use a fake model (`tests/test_live_session.py`). Browser tests (`web/tests/dashboard.spec.ts`) use `clinic_voice_receptionist.testing.ScriptedConnector`, installed by `apps/api/tests/browser_server.py`, and a fake microphone. Create the disposable database once: `CREATE DATABASE clinic_e2e OWNER clinic_owner`, grant CONNECT to the other roles, run `alembic upgrade head` with `DATABASE_OWNER_URL` pointing at it, then set the three `TEST_*_URL` variables.
- **Phone numbers** (`clinic_voice_receptionist/numbers/`, table `voice.phone_numbers`, REST under `/inbound/numbers`, screen at `/voice-receptionist/numbers`): staff search Twilio for US local or toll-free numbers (free), buy one, assign it to an active agent or leave it unassigned, and release it. Only managers can search, buy, assign or release (buying costs money: each clinic is capped at `VOICE_MAX_NUMBERS_PER_CLINIC`, default 2, checked under a per-clinic advisory lock so two clicks cannot both pass). Twilio is called with plain HTTPS using the shared `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`; a purchase is never retried, and if the number cannot be saved afterwards (duplicate, or the commit fails) it is given back to Twilio. A number belongs to one clinic ever (`number` and `provider_sid` are globally unique). Releasing calls Twilio first and removes the row only once Twilio has let go. If `VOICE_PUBLIC_API_URL` is set, a bought number's voice webhook is pointed at `/features/voice_receptionist/twilio/voice`, and saving a number's routing re-points it. The address is also kept right automatically: `Feature.on_startup` (a generic hook the API runs in the background at each start, where a failure is logged and ignored and never delays serving) runs `numbers/sync.py`, which lists the Twilio account's numbers (one call), and re-points every number in this server's own database whose address differs from the configured one. Numbers on the account that this database does not own are never touched, and with no address or no Twilio details it does nothing. So a new deployment address, or a restarted ngrok tunnel plus an API restart, needs no manual step. Tests use `testing.FakeNumbers`, and `apps/api/tests/browser_server.py` installs it so browser tests never reach Twilio. In production Terraform adds `TWILIO_AUTH_TOKEN` (Secret Manager) and `TWILIO_ACCOUNT_SID` to the API only when `twilio_enabled = true` in `envs/prod.tfvars`, after the GitHub environment `production` has the `TWILIO_AUTH_TOKEN` secret and `TWILIO_ACCOUNT_SID` variable.
- **Phone calls** (`clinic_voice_receptionist/twilio_calls/`): Twilio calls `POST /features/voice_receptionist/twilio/voice` when someone dials a bought number. The route has no staff session, so it sits in the feature's `websocket_router` (mounted without the sign-in dependencies) and trusts a request only if `X-Twilio-Signature` matches (`signature.py`; computed over the configured `VOICE_PUBLIC_API_URL` + path, not the address the server sees, and checked against Twilio's own library). It finds the clinic and agent from the dialled number (the one lookup that uses the system role), refuses politely (spoken message, hang-up) when the number is unknown, has no agent, the agent is off, the feature is not enabled or the server is full, creates a `voice.calls` row (`channel=twilio`, `from_number`, `to_number`, `provider_call_id`; Twilio retrying the webhook reuses the same row), and answers with TwiML `<Connect><Stream>` to `/features/voice_receptionist/twilio/stream` carrying a one-time ticket as a custom parameter. `stream.py` reads Twilio's `start`, redeems the ticket (which must belong to that CallSid), and runs the same `CallSession` as browser calls through `PhoneTransport`, so tools, knowledge search, variables, recording and history all work unchanged. Audio is converted in `audio.py` without `audioop`: Twilio's 8 kHz mu-law to 16 kHz PCM16 in, 24 kHz PCM16 to 8 kHz mu-law out; an interruption sends Twilio a `clear` so buffered speech stops. `inbound/call_setup.py` (snapshot and stale-call expiry) is shared with test calls, and `ws.run_session` runs a call over any transport. Locally Twilio needs a public address: run `ngrok http 8000`, set `VOICE_PUBLIC_API_URL` to its https address and add its host to `TRUSTED_HOSTS` (a free ngrok address changes on restart, so update both and save each number's routing again). `VOICE_ALLOW_SIP_TEST_CALLS=true` (local only, default false) lets the webhook read the dialled number from a SIP address, for testing with a softphone such as Linphone through a Twilio SIP domain whose voice URL is this webhook. Use made-up details only until the BAAs with Twilio and Google are in place. For production set `min_instances` to 1 so the first call after idle does not wait for a cold start.
- **Knowledge base** (`packages/knowledge`, tables `knowledge.documents` and `knowledge.chunks`, UI at `/voice-receptionist/knowledge`, REST in `clinic_voice_receptionist/knowledge/router.py`): clinics upload PDF/Word/text/Markdown files (stored under `knowledge-base/<tenant>/<document>/` in the files bucket), which are read, split into passages and embedded (Vertex `text-embedding-005`, 768 dims, `halfvec` in pgvector). Deleting a document deletes its passages by `ON DELETE CASCADE` and then its stored file. Status is `uploaded`, `processing`, `ready`, `failed` or `duplicate`; the same file (SHA-256) is refused, a different file with the same name asks Replace or Keep both, and the same text under another file name is marked `duplicate`. Limits per clinic are in `KnowledgeSettings` (20 files, 5 MB, 5,000 passages) to stay on `db-f1-micro`. The upload commits before the job is queued, because the job runs on its own connection. With no queue configured (local, tests) the job runs inside the API process (`clinic_knowledge.queue`). In production (`KNOWLEDGE_TASKS_QUEUE` and `KNOWLEDGE_INGEST_URL` set by Terraform) the API puts a task on the Cloud Tasks queue after the upload commits, and Cloud Tasks calls the private `prod-avishkar-ingest` Cloud Run service (`apps/worker`, `clinic-ingest`, `POST /tasks/knowledge/ingest`, its own image from `apps/worker/Dockerfile`). That service checks a Google-signed token from the queue's service account, answers 2xx once a document is ready, failed or duplicate and 503 while it is still in progress (so Cloud Tasks retries, up to 5 times), and a task that cannot even be created marks the document failed. Documents stuck in `processing` after a crash are picked up by the next retry; there is no separate sweeper yet. Search (`clinic_knowledge/search.py`) embeds the question (cached), then one SQL statement merges vector similarity and keyword matches by reciprocal rank fusion, drops anything below a relevance threshold (measured against real embeddings: 0.58, or 0.45 with a keyword match) and repeated passages, and runs in the caller's tenant session. Passages that already exist in another document are not stored again at ingest. Agents reach it through the internal tool `search_knowledge` (`clinic_voice_receptionist/knowledge/lookup.py`, 4 s limit, three passages, always returned with a note that they are reference text and not instructions, and a 'do not guess' note when nothing matches); staff try it with Test search on the Knowledge page (`POST /inbound/knowledge/search`). A clinic adds the tool from the tool catalog like any internal tool. Embedding a question takes 0.4 to 1.9 s from a laptop, which is the main latency cost; caching and a keyword fallback are planned. Needs pgvector: `pgvector/pgvector:pg17` in Docker and CI; on an existing local database run `CREATE EXTENSION vector` once as a superuser. On Cloud SQL the migration creates it itself, because `clinic_owner` is a member of `cloudsqlsuperuser`.
- Authentication tables are global in the `auth` schema, using the restricted `clinic_auth` role. Tenant feature data continues to use the `clinic_app` connection and RLS; narrow cross-tenant membership/provisioning operations use `clinic_system`.
- The ignored root `.env` is the local configuration source. Configure all four database URLs (`DATABASE_OWNER_URL`, `DATABASE_URL`, `DATABASE_SYSTEM_URL`, `DATABASE_AUTH_URL`), Google credentials, public origin and callback. Keep secrets out of frontend variables and Git.
- Start Docker Postgres/Redis, initialize `clinic_auth` for an existing volume with `infra/postgres/auth-role.sql`, then run `pnpm db:migrate`. If changing `POSTGRES_PORT`, match all local database URL host ports. Restart backend/frontend after configuration changes.
- Voice agents, calls, numbers, tools and test calls currently use explicitly simulated data. Live voice APIs and audio runtime are future work. The source `agent/`, `jobs/` and `infra/` contained only placeholders; `apps/voice-agent` has not been created.
- Source credentials and database records were not copied. The original checkout remains intact.
- Browser tests require a disposable migrated database with `TEST_DATABASE_URL`, `TEST_AUTH_DATABASE_URL` and `TEST_SYSTEM_DATABASE_URL`. Run `pnpm --filter @clinic/web test:e2e` separately from the production build or another Next dev server in the same checkout.

Layers run apps → features → integrations/engagement → core → db. Features never import each other; they talk through `core` tables and `emit()` events. `pnpm boundaries` enforces this, so a new package must be added to the import-linter lists in the root `pyproject.toml` and to the uv workspace `members`/`sources`.

## Migrations

All tables live in `packages/db`. One stream, one head. No other package creates tables.

1. Edit or add `packages/db/src/clinic_db/models/<schema>.py`; import it in `models/__init__.py`.
2. `pnpm db:revision "short description"`, then **read the generated file**.
3. For every new table with `tenant_id`, add `enable_tenant_rls(op, "<schema>.<table>")` after its `create_table`. A new schema needs `create_schema_with_grants(op, "<schema>")` first. Both helpers are in `clinic_db/rls.py`; a test fails if RLS is missing.
4. `pnpm db:migrate`, then `uv run alembic check` (inside `packages/db`) to confirm models and migrations match.
5. `pnpm --filter @clinic/db check-heads` must report a single head. Two open PRs that both add a migration fork the history: rebase and set `down_revision` to the current head.

Rules:
- A migration that has been merged is immutable; fix forward with a new one.
- Migrations run while the old API and worker are still serving, so keep each one backward compatible (add columns nullable or defaulted; drop in a later release).
- Enum-like values are plain strings validated in Python, and per-client extras go in `attributes` JSONB, so many changes need no migration.

How it reaches production: every merge to `main` that touches app code runs `deploy.yml`, whose `migrate` step does this before any service is deployed (`migrate.yml` is only for running a migration by hand). It builds `packages/db/Dockerfile`, takes a Cloud SQL backup, points the Cloud Run Job at the new image, and executes it. The image runs `bootstrap_roles` (creates `clinic_app` and `clinic_system` once; never rotates their passwords) and then `alembic upgrade head`. There is no approval step. Terraform manages the `clinic_auth` password and auth connection URL in Secret Manager. The migration job receives `CLINIC_AUTH_PASSWORD`; role bootstrap creates the restricted login or enables an existing NOLOGIN placeholder without rotating existing login passwords. Backend deployments must grant their service account access to the `auth-url` secret and inject it as `DATABASE_AUTH_URL`. Local `auth-role.sql` is for development only.

## Infra (`infra/terraform`)

Layout: root files wire modules together; `modules/<name>/{main,variables,outputs}.tf` holds resources; `envs/<env>.tfvars` and `envs/<env>.backend.hcl` hold per-environment values.

- **Naming:** every resource is named from `local.name` (`<environment>-avishkar`), so prod resources start `prod-`. Pass `name = local.name` and `labels = local.labels` into each module and build names as `"${var.name}-<thing>"`.
- **Environments:** one codebase, one state prefix per environment in the shared GCS bucket. All share one GCP project, so the name prefix and the `environment` label are what separate them.
- **Add a resource:** create `modules/<name>/`, call it from `main.tf`, and expose only what other modules need through outputs. Add any new GCP API to the `google_project_service` list in `main.tf`.
- **Add an environment:** add `envs/<env>.tfvars` and `envs/<env>.backend.hcl`. `terraform.yml` hardcodes `TF_ENV: prod`, and the subnet range is not yet a root variable; give each VPC a distinct CIDR when you add that variable.
- **Sensitive values** (API keys, tokens, anything not generated by Terraform): never put them in `*.tfvars` or the repo. Store the value as a GitHub **repository secret**, declare the Terraform variable with `sensitive = true`, and pass it in the `terraform.yml` plan and apply steps as `TF_VAR_<name>: ${{ secrets.<NAME> }}`. Then have Terraform write it to a `google_secret_manager_secret` plus version in GCP, and let services read it from there. Non-sensitive values (project, region, environment) stay in `envs/<env>.tfvars`.
- **Secrets:** generated with `random_password` and stored in Secret Manager. Anything referencing a secret's `latest` version must depend on the version resource, not just the secret, or Cloud Run fails with "was not found".
- **Files:** one private bucket (`modules/storage`, `<name>-<project>-files`, public access prevented, never auto-deleted). Each feature uses its own folder. Voice recordings go under `voice-recordings/<tenant_id>/<call_id>.wav`: the API's service account (`roles/storage.objectUser`, this bucket only) can reach every tenant's files and row-level security does not apply to storage, so the code must build every path from the authenticated tenant, never from request input, and check a call belongs to the tenant before reading its file. The bucket name reaches the API as `VOICE_RECORDINGS_BUCKET`.
- **Cloud Tasks:** the CI service account needs `roles/cloudtasks.admin` (a one-time grant by hand) before Terraform can create the queue and its IAM.
- **Image:** Terraform creates the Cloud Run Job with a placeholder image and ignores image changes; `migrate.yml` sets the real image. The job must exist (Terraform applied) before `migrate.yml` can run.

### Deployed apps (Cloud Run)

- Three Cloud Run services: two public, `prod-avishkar-api` (FastAPI: also the call WebSocket; scales to zero for now (set `min_instances` to 1 before real callers, or the first call after idle waits for a cold start), 50 calls per instance, 1 hour request timeout, Direct VPC egress to Cloud SQL) and `prod-avishkar-web` (Next.js standalone). and a private third, `prod-avishkar-ingest` (knowledge-base ingestion: scales to zero, one file per instance, at most 2 instances, 10 minute limit, Direct VPC egress, no public access; only the `queue` service account may call it, Cloud Tasks queue `prod-avishkar-knowledge-ingest` rate-limited to 2 concurrent calls to protect the small database). Public addresses follow a fixed pattern (`<service>-<project number>.<region>.run.app`), so each is known before it exists; that is how the API gets the web origin for sign-in and the web build gets the API address.
- `deploy.yml`: on a merge to `main`, build the `api`, `web`, `migrate` and `ingest` images, run migrations, deploy the ingest service (no smoke test: it is private; the update itself fails if the new revision cannot start), then the API, then the web app, each followed by a smoke test (`/api/v1/health/ready`; `/login` and `/api/v1/health/live` through the web app's rewrite). Pull requests only check that the images build. Terraform creates the services with a placeholder image and ignores image changes; the workflow sets the real one. On a new project, apply Terraform before the first deploy. To roll back, `gcloud run services update-traffic <service> --to-revisions <previous>=100`.
- Settings: plain values are `env` in `services.tf`; anything sensitive is a Secret Manager secret that Cloud Run injects (`api_secrets`). Terraform generates the database URLs, `VOICE_SECRETS_KEY` and permanent `EMAIL_PAYLOAD_ENCRYPTION_KEY`. A credential from outside enters as a secret of the GitHub Environment `production`, then `TF_VAR_*` in the jobs of `terraform.yml` that declare `environment: production`, then a secret and version in `secrets.tf`, then an entry in `api_secrets`. The ingest service gets the same production settings as the API (the shared settings check demands them) but only `DATABASE_URL` and `GOOGLE_CLIENT_SECRET`. External credentials include `SENDGRID_API_KEY` (required with invitations), optional `EMAIL_OLD_PAYLOAD_KEYS` (enable the compatibility secret before key adoption/rotation), and `GOOGLE_CLIENT_SECRET` (environment secret) and `GOOGLE_CLIENT_ID` (environment variable). Values that differ per environment live in that environment, so dev and uat are the same names with different values; project-wide values (`PROJECT_ID`, `REGION`, `WIF_PROVIDER`, `CICD_SA`) stay repository variables while they share one project. Keep the environment's deployment branches unrestricted, or the pull-request plan cannot read its values. Secrets are read when an instance starts, so after changing one, deploy again.
- The web image bakes in `BACKEND_INTERNAL_URL` and `NEXT_PUBLIC_API_URL` at build time, so an image belongs to one environment. Add `terraform output google_oauth_redirect_uri` to the Google OAuth client by hand.
- The API sets `TRUSTED_PROXY_HOPS=1` and reads the real client address from the right of `X-Forwarded-For` (`clinic_api.forwarded`). Without it every user would share one login rate limit. Cloud Run replaces instances on a deploy, so a deploy can end calls in progress; release outside busy hours.

Deploy flow: PRs touching `infra/terraform/**` run fmt, validate and plan (shown in the run summary). A merge to `main` runs plan and apply automatically. The org is on GitHub Free, so there are no required reviewers and no branch protection: the PR review is the only gate.

Gotchas:
- Created by hand, outside Terraform: the state bucket, the Workload Identity pool/provider, and the `github-cicd` service account. Do not recreate them in Terraform without importing.
- Repo variables `PROJECT_ID`, `REGION`, `WIF_PROVIDER`, `CICD_SA` hold the bare value only. `WIF_PROVIDER` must start with `projects/`; a leading `=` or `WIF_PROVIDER=` breaks authentication.
- The database has a private IP only. Reach it through the Cloud Run Job or Cloud SQL Studio, not from a laptop or a GitHub runner.
- Generated passwords are in the Terraform state; keep the state bucket private.

## Checks before a PR

`pnpm lint`, `pnpm test`, `pnpm boundaries`, and `pnpm typecheck` (needs the local DB from `pnpm db:up` and `pnpm db:migrate`). After an API change run `pnpm api-client:generate` and commit the result. For infra: `terraform fmt -recursive` and `terraform validate` from `infra/terraform`.

Workspace invitations and email delivery setup: [docs/USER_MANAGEMENT.md](docs/USER_MANAGEMENT.md). Keep sender credentials server-side and use the shared email templates/service.
