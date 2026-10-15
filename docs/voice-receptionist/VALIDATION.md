# Migration verification - 12 October 2026

- 49 Python tests passed: existing platform/import/reactivation coverage, copied Google auth tests, session lifecycle, onboarding concurrency, tenant selection, CSRF, entitlement denial and restricted auth-role access.
- All 8 copied/adapted Playwright journeys passed, including responsive layouts at 1440/820/390 widths, agent drafts/publish/number routing, simulated calls, variables/tools, filters/export, missing records, dialog/tab keyboard behavior and session expiry/outage. An obsolete tenant cookie from the old parent UI is covered.
- Production Next build passed for all platform/auth/voice routes.
- Workspace TypeScript checks, web ESLint, Python Ruff lint/format, and all three architecture import contracts passed.
- One Alembic head (`20261012_0002`); database models match migrations (`alembic check`).
- Generated API types were regenerated again and confirmed unchanged.
- Docker Compose configuration parses successfully. Container image build/runtime was not executed.
- Every original file under the source `docs/` was copied byte-for-byte, including the blueprint PDF. Additional source READMEs were archived with repaired documentation links.

Tests used an isolated temporary PostgreSQL server on port 55439 with separate app/auth/system roles. The minimal test PostgreSQL distribution does not ship pgcrypto. The test bootstrap skipped only the initial migration's optional `CREATE EXTENSION pgcrypto` statement and used PostgreSQL's built-in `gen_random_uuid`; every table/grant/RLS/auth migration operation ran normally. The repository migrations retain the extension statement for the documented PostgreSQL 17 deployment. The temporary server was shut down after verification.

Browser tests use a test-only simulated identity provider. Real Google consent/token exchange in this merged checkout, production HTTPS, and live voice remain separate acceptance work. The source implementation has no live voice runtime or voice CRUD backend to migrate. One non-failing Authlib warning notes its legacy httpx import namespace; copied provider behavior is covered by signed-token tests.

No source database, credentials, generated caches or nested Git repository were copied. The source checkout remains intact. See [current setup](README.md) for root environment configuration and the auth role step for existing parent database volumes.

## Voice shell restoration

Restored the original Avishkar sidebar, workspace identity, profile, breadcrumbs, header actions, footer and desktop scale. Voice routes replace the parent shell; a return link preserves access to other clinic products. Scoped browser defaults protect source typography from Tailwind preflight. Nine browser journeys passed against a separate `voice_ui_test` database, including shell geometry and navigation to/from the platform at 1440, 820 and 390 pixels. Desktop and mobile screenshots were visually inspected.

## Pre-merge review fixes — 15 October 2026

- Rebased onto main including reactivation settings/runs. Auth migration now follows `ba9df5563ea9`; one Alembic head remains. A fresh Docker PostgreSQL database upgraded through the complete chain, and `alembic check` reports no model drift.
- Shared Brand/Field/Select/FormError now live in `packages/ui/src/auth.tsx`; platform authentication styles are in `packages/ui/styles/auth.css`, and branding is under `apps/web/public/brand`. Login/onboarding and root metadata have no imports or assets from the voice feature.
- Voice pages moved to `apps/web/app/(fullscreen)/voice-receptionist`; the fullscreen group provides shared authentication, while the platform frame has no feature path checks. URLs and entitlement enforcement are unchanged.
- All nine voice browser journeys passed. A new independent platform-auth browser test also passed with voice routes, components, libraries, stylesheet and voice tests temporarily removed; the platform production build passed in that state. All removed files were restored automatically.
- All 63 Python tests passed across API, shared auth, DB bootstrap, reactivation and integrations. Normal production build, web/shared UI typechecks, ESLint, Ruff and import boundaries passed. This frontend-removal smoke check does not claim complete backend-package removal coverage.

Follow-up after merge: move voice frontend implementation/tests into `packages/features/voice-receptionist/web/` with thin app routes; agree and implement live voice API contracts. New features must already follow the feature-owned `web/` convention. The full package/route/entry-point removal acceptance check belongs to that modularization follow-up.

## Complete feature modularization — 15 October 2026

This supersedes the earlier note deferring frontend modularization. Voice now owns `web/pages`, `web/components`, `web/lib`, `web/styles` and `web/tests` below its feature package. App routes are thin package exports. Shared session/API helpers live in `packages/core/web`; shared auth controls/styles and branding remain independent of voice. Voice-only backend entitlement assertions also moved into the voice package. Trial enrollment uses discovered `trial_eligible` metadata instead of a hard-coded feature list.

Validation with voice installed: production frontend build, all 64 workspace Python tests, all 10 browser journeys, web/core/voice/UI typechecks, ESLint, Ruff and Python/frontend import boundaries passed.

Full removal acceptance passed in an isolated temporary copy, twice: removed the entire `packages/features/voice-receptionist` directory, its route folder and explicit npm/Python/import-linter registrations; refreshed lockfiles and installed a separate virtualenv. The remaining platform passed `pnpm build`, `pnpm test` (63 Python tests), `pnpm boundaries`, `pnpm typecheck` and its platform-only Google-provider/onboarding/sign-out browser test. The source checkout and shared database migrations were preserved. The repeatable check is `scripts/check_voice_removal.py`, now run by CI after regular browser tests. The only functional follow-up is the separately scoped live voice API/runtime implementation.
