# User management: PR validation

Validation dates: 23–24 October 2026. Branch: `user/management`.

The 24 October review follow-up below supersedes the historical three-failure
result: the full Python suite now passes (853 tests). Earlier sections retain the
checks performed at each stage rather than implying every historical count is current.

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

### Legacy audit actor names

A local historical invitation-acceptance event used an account ID instead of a
workspace member ID. The name resolver now accepts either ID through memberships
in that workspace only, including inactive memberships. It never searches the
global user directory for unmatched audit IDs. Table, actor options and CSV share
the resolver; unresolved staff actors show “Unknown member” while CSV preserves
the original actor ID. Audit rows are not rewritten.

The auth/invitation/workspace suite passes **22 tests**, including a regression for
both ID formats and preventing names from a different workspace being exposed.
Targeted Ruff and diff checks pass.

## Review follow-up (24 October 2026)

Rebased onto `origin/main` at `38e06c7` (Knowledge Base / PR #17), preserving its
routes, schema, ingestion service and Next.js 16.4.2 update. The membership
migration now follows `85fd3f8a4f12`; `20261023_audit_history` remains the only head.

| Review point | Resolution |
| --- | --- |
| Three Voice URL-validation failures | Root conftest pins `VOICE_TOOL_ALLOW_PRIVATE_HOSTS=false`; an additional runtime validator rejects the override in production. All 13 validation cases also pass with a deliberately true parent environment. |
| Provider / Consultant feature access | Intentionally reserved and denied by default; workspace/account basics only. This is explicit in the permission matrix and invitation plan. No extra clinical permissions were granted. |
| Recovery identity and frequency | Dedicated `prod-avishkar-email-worker` cloud account, access to only the system DB URL and two email secrets, no bucket/OAuth secrets. The standalone worker uses an email-only validated settings class. Scheduler runs every five minutes. |
| Slow immediate submission | Five-second outer budget instead of twenty, still awaited after commit. A cancellation regression proves the encrypted delivery remains recoverable. A post-response background task is deliberately avoided on request-scoped Cloud Run CPU. |
| CSV leading control characters | Leading tab and carriage return are escaped even without a formula; formula-prefix escaping remains. |
| BYPASSRLS management endpoints | Foreign-workspace and mismatched-ID regressions cover settings, member listing/update/removal, invitation creation/list/resend/revoke, audit options/history and CSV export. |
| OFFSET at high page numbers | Removed OFFSET and arbitrary page numbers; audit pages use scoped event-ID cursors and `(occurred_at, id)` keyset comparisons. UI Previous/Next keeps a cursor stack and still shows 50 rows. |
| Invitation delivery N+1 | One scoped delivery query for the pending invitation batch; a query-count regression verifies five invitations use one delivery SELECT. |
| Next security patch | Preserved main's Next.js 16.4.2; aligned dependency minimums and regenerated the frozen lockfile. The [reported Server Actions advisory](https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r) lists 16.4.1 as patched; it does not establish that 16.4.1 is affected. |
| Production sender configuration | Enabled invitations and added the requested verified sender/name/reply-to in prod.tfvars. Existing email secret containers are adopted using declarative imports; values stay outside Terraform state. |

Validation on the updated code:

- Full Python suite: **843 passed**, one existing Authlib deprecation warning.
- Focused new/affected regressions: **44 passed**.
- Explicit true-parent-environment Voice URL regression: **13 passed**.
- Frontend unit suite: **97 passed, 1 optional mutool check skipped**, no failures.
- Frozen pnpm installation, uv frozen sync, API type regeneration, web typecheck,
  web ESLint, repository Ruff check/format, architecture boundaries and Terraform
  recursive formatting/validation pass.
- Fresh isolated pgvector PostgreSQL 17 database migrated through the combined
  chain; Alembic reports no model drift. Development data was not reset.
- Full browser suite: **88 passed**, including Knowledge Base, invitations, cursor
  navigation/filter/export, workspace restoration and the no-JavaScript onboarding
  guard. The browser-only echo fixture deliberately allows localhost; routine
  Python tests pin that override off.
- The rebased onboarding hydration guard uses `useSyncExternalStore`, preserving
  disabled-until-hydrated behavior while satisfying the current lint rule.
- Production frontend build with Next.js 16.4.2 passes.
- Final GitHub CI is triggered by pushing this review commit; consult PR #16 checks
  for its current result rather than treating the older green head as validation.

No Terraform plan/apply, secret-value read/write or production deployment was
performed. The secret containers/versions are assumed to exist as confirmed by the
user. Run Terraform before deploying the new recovery job image. Settings and
permission tests do not replace a production delivery smoke test.


## Cloud Tasks follow-up (24 October)

Production email now follows Knowledge Base's Cloud Tasks/private HTTP worker
pattern. After commit the API publishes only a delivery UUID; the OIDC-authenticated
worker loads the encrypted record and submits to SendGrid. Database leases and
terminal statuses handle duplicate tasks. The five-minute recovery job republishes
missing/stale tasks rather than sending production email directly. Local queue
configuration remains empty and retains direct sending plus worker recovery.

Final verification:

- Full Python suite: **853 passed**, one existing Authlib deprecation warning.
- Focused auth/Cloud Tasks suite after the final RPC timeout change: **35 passed**.
- Platform browser journeys: **4 passed**; the prior full browser run was 88 passed.
- Fresh isolated PostgreSQL migration and Alembic drift check passed; one head
  `20261024_email_tasks`.
- Ruff, architecture boundaries, generated API schema comparison, Terraform
  formatting and validation passed.
- Fixed a randomized reactivation differential-test fixture responsible for the
  previous CI failure. Three separate fresh processes passed the unchanged assertion.
- Local Docker dependency downloads stalled; image validation must be confirmed
  by the new email image CI build rather than reported as locally successful.

Deploy requires Terraform provisioning of the queue, private sender and identities,
then the release workflow's email image deployment before the API release. No
production infrastructure was applied or email sent during these tests.
