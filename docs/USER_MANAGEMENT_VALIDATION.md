# User management: PR validation

Validation date: 23 October 2026. Branch: `user/management`.

This records local verification of the invitation, membership and transactional
email changes. It establishes readiness for code review, not a guarantee that
all security defects are absent or that production infrastructure is configured.

## Isolation and reproducibility

- Node 24, Python 3.12, pnpm 9.15.9, PostgreSQL 17 and Redis 7.
- Fresh disposable `pr_validation_20261023` database, migrated from base to head.
  Development workspace data was not reset or used for test fixtures.
- Automated tests disable live email credentials. Provider calls are mocked or
  captured; Google identities, model calls and voice recordings are simulated.
- Tests were run through the repository CI commands, including the uncached
  `pnpm turbo run typecheck test build --force --output-logs=errors-only` task graph.
- Browser fixture helpers use `TEST_*` URLs and preserve their database-isolation
  guard. Role journeys assign actual disposable memberships rather than spoofing
  browser-only authentication responses.
- `origin/main` was fetched and the branch already includes its current commits.

## Completed checks

| Check | Result |
|---|---|
| `pnpm install --frozen-lockfile`, `uv sync --frozen` | Pass |
| Full CI typecheck/test/build task graph | 13 tasks pass, without cache |
| Python package suites | 775 tests pass; final direct rerun also 775 pass after audit fix |
| Reactivation frontend unit suite | 98 cases: 97 pass, 1 optional `mutool` check skipped |
| Workspace lint tasks | 15 tasks pass, including web ESLint |
| Ruff check and format check | Pass |
| Python and frontend architecture boundaries | Pass |
| Alembic fresh install, downgrade to prior head, upgrade to new head | Pass |
| Alembic model drift | No new upgrade operations |
| Alembic heads | Single head: `20261023_membership` |
| API type regeneration | Generated schema unchanged |
| Terraform recursive format and validation | Pass; no plan/apply |
| API, frontend and migration Docker image builds | Pass |
| API image email/template import smoke test | Pass |
| Browser journeys | 85 tests pass across platform, reactivation and voice (5.4 minutes) |
| Voice feature-removal validation | Pass: build, 597 Python tests, 98 frontend unit cases, boundaries, types and 71 browser journeys |

The complete Python suite also ran directly before the additional office-manager
regression was added: 774 tests passed. The final package task graph includes that
regression (775 total). A parallel-test assumption about global tenant counts was
corrected to assert the recipient's actual memberships instead.

## Authorization and delivery coverage

The new integration coverage verifies:

- acceptance joins the original workspace and does not grant a new owner workspace;
- existing users can join another workspace without inheriting rights from their
  other memberships, and cannot select an unauthorized workspace;
- matching authenticated email, fresh login and, where needed, a fresh mailbox code;
- CSRF/origin checks, forbidden Owner invitations, and rejection of extra role fields;
- office-manager grant limits, protected Owner/self membership, role demotion,
  removal, and cancellation of pending grants after their inviter loses authority;
- cross-workspace denial and runtime-role RLS hiding invitations and email records;
- concurrent acceptance, replay, expiration, resend token rotation and revocation;
- correct staff actor IDs and entity types in acceptance/member-change audit records;
- encrypted queue payloads and HTML-escaped email content;
- immediate delivery only after commit, targeted dispatch despite older backlog,
  concurrent dispatch leases and durable retry after SendGrid 429 responses.

The code review also checked that client visibility is backed by API permission
checks; sessions select workspaces on the server; token/context hashes are stored
instead of bearer tokens; queued content is encrypted and bound to its delivery
and tenant; provider diagnostics do not leak credentials/content; and invitation
pages set CSP, no-referrer and no-store policies. Privileged voice work rechecks
current session/membership instead of retaining privileges indefinitely.

## Dependency audit

Security validation found and patched existing dependency advisories:

- Next.js, `@next/env`, `eslint-config-next` and workspace Next.js peer requirements
  now use 16.4.1, removing vulnerable 16.4.0 copies from the lockfile.
- The Python lockfile now uses certifi 2026.10.19 instead of the affected older CA
  bundle. The installed Python dependency audit reports no known vulnerabilities.

Final JavaScript audit: **zero critical, one high**. The remaining issue is
[`braces` GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm),
reached through `eslint-config-next` → Next ESLint plugin → `fast-glob` →
`micromatch`. It is a development lint-tooling dependency; no patched release was
published at validation time. It has not been suppressed or misreported as fixed.
Avoid feeding untrusted glob patterns into that tooling and track the upstream
fix. This remains an explicit review consideration.

## Release gates and limits

- Production SendGrid/encryption secret versions, verified sender configuration,
  the invitation feature flag and recovery job still require deployment rollout.
  See [USER_MANAGEMENT.md](USER_MANAGEMENT.md#production-rollout).
- No production deployment or Terraform apply was performed. Terraform validation
  and Docker builds do not substitute for an environment-specific plan and smoke test.
- Live Google/HTTPS and production email deliverability need a staging/production
  smoke test. The earlier local invitation was accepted by SendGrid; that is not
  proof of delivery in production.
- SendGrid 202 means provider acceptance, not inbox delivery. Signed delivery
  webhooks are not implemented. Ambiguous HTTP failures can cause duplicate email
  submissions; membership acceptance remains idempotent.
- Existing Authlib HTTPX deprecation warnings remain non-failing.
- These checks are not a penetration test or a promise of zero security flaws.

## Review readiness

All required local checks completed successfully. The branch is ready to raise
for PR review with the development-tooling advisory explicitly disclosed above.
Production readiness remains conditional on the listed environment rollout and
smoke tests. No push, pull request creation, deployment or infrastructure apply
is implied by this local sign-off.

## Re-invitation follow-up

Removed members can now receive a fresh invitation and reactivate their existing
membership only after the original Google identity accepts. The new invitation
sets the restored role. Removal revokes older outstanding invitations to that
email; old accepted links cannot reactivate an inactive member. Original manager
roles remain protected against lower-role re-invitation by an office manager.
No database migration is introduced.

Follow-up verification: **777 Python tests** (including **20 auth/invitation
integration tests**) pass. The extended browser journey removes a member,
re-invites them, verifies access is still denied while pending, then accepts and
checks the original user/workspace/membership IDs are preserved. It passes.
TypeScript, ESLint, Ruff checks, production build and boundaries pass. The earlier
full browser/removal runs above describe the base implementation; this follow-up
reruns the affected complete invitation journey rather than claiming a new run of
all 85 browser tests.

## Browser rate-counter isolation follow-up

- Only the browser-test entry point assigns synthetic per-cookie-jar client
  addresses. The real login/callback limiter remains enabled within each context.
  No limiter is disabled and no database counters are manually reset.
- A regression run twice against the same database confirms a context hits 429 at
  the real threshold while a fresh context can log in. The same regression also
  confirms changing the test cookie cannot bypass the normal application's IP limit.
- The targeted API run passes 21 tests (20 invitation/auth plus the new isolation
  regression). The full browser suite also passes all 85 tests without manual
  counter resets.

### Latest full Python rerun

The subsequent full rerun completed with **775 passed and 3 failed**. All three
failures are `test_bad_tool_definitions_are_refused_with_a_message_staff_can_act_on`
(`change0-HTTPS`, `change2-not public`, `change3-not public`) in the Voice tools API
suite: requests expected to return 422 instead returned 201. Root cause has not
been established in this audit review. This run does not establish a clean full
suite or release readiness; the failures need investigation before merge.

## Audit history follow-up

The Settings audit table now has 50-row pages, inclusive workspace-local date
filters, exact Actor/Event filters and CSV downloads of all matching history.
The CSV endpoint uses 500-row batches, a fixed maximum event ID and the same
workspace manager checks; CSV text is protected against spreadsheet formulas.
A concurrent tenant/time/ID index migration supports the history queries.

Validation for this follow-up:

- Auth/invitation/workspace API suite: 21 passed, including the new audit regression.
  It covers 556 events, tied timestamps, page boundaries, timezone day boundaries,
  combined filters, exports crossing the 500-row batch boundary, formula escaping,
  invalid inputs, foreign workspace denial and all five membership roles.
- Existing Settings browser journey passed. The new audit browser journey passed
  pagination, actor/event filters, full-history and date-filtered CSV downloads,
  clearing filters and mobile layout.
- Production frontend build, TypeScript, web ESLint, targeted Ruff checks/format,
  architecture boundaries and the single migration-head check pass. The index migration was applied to the
  disposable validation database.
- Browser tests use a separate Next output directory so local development can
  continue while those tests run. Node runtime configuration was not changed.

The earlier three Voice tool URL validation failures remain outside this change;
this follow-up does not claim a clean full-repository test rerun.
