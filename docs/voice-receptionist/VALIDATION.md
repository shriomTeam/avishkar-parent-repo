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
