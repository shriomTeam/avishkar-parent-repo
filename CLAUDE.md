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
        import/                patient data import
        (features)/
          blueprints/          existing patient blueprint pages
          reactivation/        existing reactivation pages
    components/
      auth/                    onboarding and sign-out controls
      voice/                   original Avishkar voice shell and screens
      platform-frame.tsx       generic platform shell (no feature path checks)
    lib/
      auth/                    verified session loading and auth provider
      voice/                   voice types, formatting, demo state and adapters
    styles/voice.css            scoped source design and responsive styling
    public/brand/               platform branding assets
    tests/voice/                Playwright auth and voice journeys
    playwright.config.ts       isolated browser-test API and frontend
  api/                         one FastAPI app; mounts installed features
    src/clinic_api/routers/
      auth.py                  /api/v1/auth/* Google login and sessions
      onboarding.py            /api/v1/workspaces clinic onboarding
    tests/auth/                auth, tenant and entitlement integration tests
    tests/browser_server.py    test-only simulated Google provider
    Dockerfile                 optional API/worker container image
  worker/                      one background worker
packages/
  db/                          all SQLAlchemy tables and one Alembic stream
    src/clinic_db/models/
      auth.py                  global identities, OAuth transactions, sessions
      core.py                  canonical tenants and staff-to-user links
    migrations/versions/       existing schema plus shared auth migration
  core/                        RLS, feature contract, entitlements, events, audit
    src/clinic_core/
      auth/                    Google provider, sessions, CSRF and repositories
      tenancy/                 verified memberships and clinic provisioning
    tests/auth/                shared auth unit tests
  integrations/                client data import
  engagement/                  shared SMS and email engine
  features/
    reactivation/src/          reactivation backend
    blueprints/src/            blueprint backend
    voice-receptionist/src/    voice backend entry point (control-plane stub)
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

Feature backend code belongs in its package's `src/`. The current reactivation and blueprints pages live in `apps/web/app/(platform)/(features)/`; voice routes live in `apps/web/app/(fullscreen)/voice-receptionist/`, with voice components and adapters namespaced under `components/voice` and `lib/voice`. New features must start in `packages/features/<name>/web/`, with thin one-line route files in `apps/web` importing their pages. The migrated voice frontend remains an explicit transitional exception; moving its screens, adapters, styles, assets and tests into `packages/features/voice-receptionist/web/` is a follow-up after merge.

## Voice AI migration

Read [docs/voice-receptionist/README.md](docs/voice-receptionist/README.md) for current setup and paths, [the migration plan](docs/voice-receptionist/VOICE_AI_MIGRATION_PLAN.md) for architecture and future phases, and [validation](docs/voice-receptionist/VALIDATION.md) for checks and limits. Archived source guides retain the old repository paths; do not use their commands for this monorepo.

- Google OAuth, opaque database sessions, CSRF and clinic onboarding are implemented in the shared API/core/DB layers. Source workspace records map to canonical `core.tenants` and `core.staff`; supplied tenant IDs must be checked against verified membership.
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

How it reaches production: merging a change under `packages/db/**` to `main` runs `migrate.yml`. It builds `packages/db/Dockerfile`, takes a Cloud SQL backup, points the Cloud Run Job at the new image, and executes it. The image runs `bootstrap_roles` (creates `clinic_app` and `clinic_system` once; never rotates their passwords) and then `alembic upgrade head`. There is no approval step. Terraform manages the `clinic_auth` password and auth connection URL in Secret Manager. The migration job receives `CLINIC_AUTH_PASSWORD`; role bootstrap creates the restricted login or enables an existing NOLOGIN placeholder without rotating existing login passwords. Backend deployments must grant their service account access to the `auth-url` secret and inject it as `DATABASE_AUTH_URL`. Local `auth-role.sql` is for development only.

## Infra (`infra/terraform`)

Layout: root files wire modules together; `modules/<name>/{main,variables,outputs}.tf` holds resources; `envs/<env>.tfvars` and `envs/<env>.backend.hcl` hold per-environment values.

- **Naming:** every resource is named from `local.name` (`<environment>-avishkar`), so prod resources start `prod-`. Pass `name = local.name` and `labels = local.labels` into each module and build names as `"${var.name}-<thing>"`.
- **Environments:** one codebase, one state prefix per environment in the shared GCS bucket. All share one GCP project, so the name prefix and the `environment` label are what separate them.
- **Add a resource:** create `modules/<name>/`, call it from `main.tf`, and expose only what other modules need through outputs. Add any new GCP API to the `google_project_service` list in `main.tf`.
- **Add an environment:** add `envs/<env>.tfvars` and `envs/<env>.backend.hcl`. `terraform.yml` hardcodes `TF_ENV: prod`, and the subnet range is not yet a root variable; give each VPC a distinct CIDR when you add that variable.
- **Sensitive values** (API keys, tokens, anything not generated by Terraform): never put them in `*.tfvars` or the repo. Store the value as a GitHub **repository secret**, declare the Terraform variable with `sensitive = true`, and pass it in the `terraform.yml` plan and apply steps as `TF_VAR_<name>: ${{ secrets.<NAME> }}`. Then have Terraform write it to a `google_secret_manager_secret` plus version in GCP, and let services read it from there. Non-sensitive values (project, region, environment) stay in `envs/<env>.tfvars`.
- **Secrets:** generated with `random_password` and stored in Secret Manager. Anything referencing a secret's `latest` version must depend on the version resource, not just the secret, or Cloud Run fails with "was not found".
- **Image:** Terraform creates the Cloud Run Job with a placeholder image and ignores image changes; `migrate.yml` sets the real image. The job must exist (Terraform applied) before `migrate.yml` can run.

Deploy flow: PRs touching `infra/terraform/**` run fmt, validate and plan (shown in the run summary). A merge to `main` runs plan and apply automatically. The org is on GitHub Free, so there are no required reviewers and no branch protection: the PR review is the only gate.

Gotchas:
- Created by hand, outside Terraform: the state bucket, the Workload Identity pool/provider, and the `github-cicd` service account. Do not recreate them in Terraform without importing.
- Repo variables `PROJECT_ID`, `REGION`, `WIF_PROVIDER`, `CICD_SA` hold the bare value only. `WIF_PROVIDER` must start with `projects/`; a leading `=` or `WIF_PROVIDER=` breaks authentication.
- The database has a private IP only. Reach it through the Cloud Run Job or Cloud SQL Studio, not from a laptop or a GitHub runner.
- Generated passwords are in the Terraform state; keep the state bucket private.

## Checks before a PR

`pnpm lint`, `pnpm test`, `pnpm boundaries`, and `pnpm typecheck` (needs the local DB from `pnpm db:up` and `pnpm db:migrate`). After an API change run `pnpm api-client:generate` and commit the result. For infra: `terraform fmt -recursive` and `terraform validate` from `infra/terraform`.
