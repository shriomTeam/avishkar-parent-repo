# Voice AI migration into the parent repository

Status: implementation reference, originally written from local inspection on 12 October 2026. The existing Google auth, onboarding and sample dashboard have now been migrated. See [current setup](README.md). New voice CRUD APIs, voice models and the live runtime remain future phases; the proposed final tree below includes those future paths.

Source: `/Users/abhinavchaudhary/Documents/Avishkar/Avishkar-Voice-AI`.
Destination: `/Users/abhinavchaudhary/Documents/Avishkar/avishkar-parent-repo`.

## 1. Recommendation

Integrate Voice AI into the parent's existing platform: one Next.js application, one FastAPI control plane, one database model registry and migration stream, and the existing background worker. Implement the voice product inside the already registered `voice_receptionist` feature. Move reusable Google authentication into shared platform code.

Do not copy the source `backend/` over `apps/api`, or `frontend/` over `apps/web`. Both destinations already contain platform functionality. Copy source files by responsibility using the mapping below, adapting imports and contracts in small verified changes.

A separate `apps/voice-agent` process is a future runtime boundary for live audio. It does not replace the API or become a second product backend. Create it when implementing the runtime; the source `agent/`, `jobs/`, and `infra/` currently contain only `.gitkeep` files.

This recommendation assumes Voice AI is a sellable component of Always-On Clinic, matching `docs/ARCHITECTURE.md`. A standalone general-purpose voice platform with its own customer lifecycle would require a separate product decision.

## 2. What exists today

| Area | Parent repository | Voice AI repository | Migration implication |
| --- | --- | --- | --- |
| Web | Next.js App Router, shared shell, reactivation, blueprints, data imports | Branded dashboard, agent editor, calls, numbers, tools, variables, test studio, settings | Port screens into the existing app; retain other platform pages |
| Backend | FastAPI dynamically discovers feature entry points | FastAPI Google auth and initial workspace onboarding | Reuse auth implementation; voice CRUD APIs must still be built |
| Identity | Dev `X-Tenant-Id`, `X-Staff-Role`, `X-Staff-Id` headers | Google identity, opaque DB sessions, CSRF, membership checks | Replace platform request identity and client transport together |
| Tenancy | `core.tenants`, RLS, feature entitlements | Separate workspaces and workspace memberships | Map workspace to tenant; avoid two tenancy systems |
| Database | Shared SQLAlchemy Base, feature schemas, one Alembic stream | Independent Base and initial auth migration in default schema | Rebuild source models on the parent Base and add parent migrations |
| Voice feature | Registered stub with `/status`, nav, `phi_sensitive=True`; `voice` schema reserved | Voice UI uses fixtures and simulated actions | Existing UI is reusable, but is not a functioning voice backend |
| Background work | Python BullMQ worker, outbox relay, schedules, engagement sends | `jobs/` empty | Register voice jobs/events through the existing feature contract |
| Runtime | None | `agent/` empty | Live calls are new implementation, not code migration |
| Tooling | pnpm + uv workspaces and root locks | npm frontend; setuptools Python backend and requirements lock | Reconcile dependencies into parent manifests and locks |
| Verification | Python integration tests, RLS tests, import boundaries, generated API checks, TS/build CI | Auth unit/integration tests and Playwright dashboard tests | Port tests and adapt database fixtures, paths, and commands |

Evidence reviewed includes the parent README, architecture and feature guide; API, worker, core, DB, feature registration, web/client configuration, CI and ownership rules; source READMEs, frontend/auth/week plans, auth models/dependencies/routes, dashboard service/state, frontend configuration/tests, and the architecture blueprint PDF. This is a migration assessment from static inspection, not a claim that every behavior has been executed or every line audited.

The older source frontend plan describes a public static preview. Current source code and READMEs supersede that: dashboard access now uses real backend sessions, while voice interactions remain simulated. The blueprint proposes LiveKit and a runtime benchmark; the week plan proposes Pipecat/Twilio. Neither proves a runtime has been implemented or settles the final transport choice.

## 3. Proposed final folder structure

Paths marked NEW are proposed. Existing files not shown stay in their current ownership areas. Avoid creating empty scaffolding before its implementation phase.

```text
apps/
  api/
    src/clinic_api/
      main.py                         existing application, mount auth/onboarding
      routers/
        auth.py                       NEW transport for Google auth/session routes
        onboarding.py                 NEW initial clinic provisioning routes
        me.py                         existing platform identity/entitlement response
        appointments.py               existing canonical booking endpoint
    tests/
      auth/                           NEW ported auth integration tests
      test_voice_flow.py              NEW feature/platform integration tests
  web/
    app/
      layout.tsx                      minimal root HTML/body and global foundations
      (auth)/                         NEW public authentication route group
        login/page.tsx
        onboarding/page.tsx
        layout.tsx                    auth layout, no clinic sidebar
      (platform)/                     NEW route group for clinic shell
        layout.tsx                    move existing clinic shell here
        page.tsx                      move existing overview here, URL remains /
        import/                       move existing import pages here
        (features)/
          reactivation/               move existing routes, URLs unchanged
          blueprints/                 move existing routes, URLs unchanged
          voice-receptionist/         NEW feature routes
            layout.tsx                requireFeature + voice state/navigation
            page.tsx                  overview
            agents/page.tsx
            agents/[agentId]/page.tsx
            calls/page.tsx
            calls/[callId]/page.tsx
            numbers/page.tsx
            tools/page.tsx
            variables/page.tsx
            test/page.tsx
            settings/page.tsx         voice-specific settings only
            guide/page.tsx
      settings/page.tsx               NEW shared account/clinic settings when needed
    components/
      auth/                           NEW login/onboarding/sign-out UI
      voice/                          NEW imported voice screen components
    lib/
      api.ts                          adapt existing typed platform client
      auth/                           NEW server lookup/provider
      voice/
        types.ts                      local view/demo types
        services/                     dashboard adapter + future API implementation
        demo/                         fixtures and mock state, explicitly sample-only
    styles/voice.module.css           NEW scoped voice design styles
    public/voice/                     NEW source logo/assets
    tests/voice/                      NEW ported Playwright journeys
  worker/                             existing background process
  voice-agent/                        NEW later: independently run live audio
    pyproject.toml
    package.json                      task wrapper consistent with Python apps
    src/clinic_voice_agent/
      main.py
      transports/                     selected audio transport adapters
      providers/                      selected speech/model adapters
      pipeline.py
      control_client.py               authenticated, scoped control-plane access
    tests/
packages/
  core/src/clinic_core/
    api.py                            verified principal -> RequestContext
    auth/                             NEW provider/session/security/repositories
    tenancy/                          NEW shared provisioning and access policies
    settings.py                       consolidate validated server settings
    events.py                         add agreed voice event contracts
  db/
    src/clinic_db/models/
      core.py                         existing tenant/staff/shared clinic entities
      auth.py                         NEW global identity/session/OAuth tables
      voice.py                        NEW tenant-scoped voice domain tables
    migrations/versions/              only authoritative migration stream
  features/voice-receptionist/
    src/clinic_voice_receptionist/
      feature.py                      existing entry point; register router/jobs/events
      router.py                       voice control-plane endpoints
      schemas.py
      services/                       agents, versions, numbers, calls, tools, variables
      repositories/                   tenant-session database operations
      jobs.py                         summaries, retention, processing
      events.py                       feature handlers
    tests/
  integrations/                       existing; add clinic/provider connectors as needed
  engagement/                         existing; all SMS/email stays here
  ui/                                 promote reusable UI only after reconciling designs
  api-client/                         generated API types, not copied handwritten contracts
infra/
  postgres/                           existing role initialization
  voice/                              NEW later: selected runtime deployment configuration
docs/
  voice-receptionist/
    VOICE_AI_MIGRATION_PLAN.md         this plan
  voice/                              NEW source design/reference docs and runbook
```

The `(platform)` move is needed because the current root layout hides all children without a tenant. Copying a `/login` page under that layout would hide login too. Route groups preserve existing URLs; update relative imports during the move and avoid duplicate `/` pages. Preserve the source voice sidebar and header on voice routes, replacing the parent sidebar there rather than nesting two sidebars. Provide a return link to the clinic platform. Other platform routes retain their existing shell.

## 4. Source-to-destination copy map

| Source | Destination/action |
| --- | --- |
| `frontend/src/app/dashboard/**` | `apps/web/app/(platform)/(features)/voice-receptionist/**`; rewrite all links, redirects, active nav and test expectations |
| `frontend/src/components/*` | Voice screens to `apps/web/components/voice`; auth/onboarding/sign-out to `components/auth`; split shared settings from voice privacy settings |
| `frontend/src/lib/auth/*` | `apps/web/lib/auth`; adapt session shape to platform tenant identity |
| `frontend/src/lib/{types,format}.ts`, `demo/*`, `services/*` | `apps/web/lib/voice`; update `@/` imports to prevent collisions |
| `frontend/src/app/globals.css` | Extract scoped voice styles; review body, aside, inputs, buttons, links and CSS variables rather than appending global CSS |
| `frontend/public/*` | `apps/web/public/voice/*`; update asset URLs and metadata |
| `backend/app/modules/auth/*` | HTTP routes into `clinic_api.routers.auth`; policy/provider/repositories into `clinic_core.auth`; models into `clinic_db.models.auth` |
| `backend/app/modules/users/*` | Global identity logic in `clinic_core.auth`; user models in `clinic_db.models.auth` |
| `backend/app/modules/workspaces/*` | Shared clinic onboarding/access policies in `clinic_core.tenancy`, routes in API; map to existing tenants/staff |
| `backend/app/api/dependencies.py` | Integrate with `clinic_core.api`; retain verified session, CSRF and membership semantics |
| `backend/app/core/*` | Consolidate with core settings/auth utilities and platform audit policy; DB models must not import core security helpers |
| `backend/app/main.py` | Merge lifespan/provider setup, headers, trusted hosts and safe errors into existing app factory; do not replace feature registration |
| `backend/app/db/*`, `backend/migrations/*` | Reference for conversion; do not copy independent Base, engine factory or migration history into production parent paths |
| Backend tests and `tests/browser_server.py` | Port to API/core tests; simulated provider remains exclusively in a test entry point |
| `frontend/tests`, Playwright config | Port to web tests; update root uv invocation, source paths, routes and isolated test ports |
| Source manifests/locks/Compose/Dockerfile | Reference for dependency/deployment consolidation, not wholesale overwrite |
| Source `docs/*` | Archive under `docs/voice/reference/`, mark historical plans and keep current run instructions in a separate runbook |

Exclude `.git`, `.env`, `.env.local`, `.venv`, `node_modules`, `.next`, caches, logs, Playwright output, local Postgres data, and generated build files. Carry placeholder settings into root `.env.example`; configure actual credentials privately. Record the source Git commit at migration start for provenance and rollback.

## 5. Critical integration decisions

### Identity and tenancy

Use one global user with a Google `(provider, subject)` identity. Sessions, OAuth transactions and rate buckets are global auth records, not voice-specific tables. Keep them in a registered `auth` schema with narrowly scoped access; extend the schema registry, migration filtering and grants. Do not apply tenant RLS blindly to global identity records. Define a restricted auth database role/access path rather than granting ordinary feature queries access to session secrets or using BYPASSRLS throughout request handling.

Map source Workspace to `core.tenants`; use `core.staff` for clinic membership by adding a nullable user FK and appropriate unique constraints through a migration. Do not reuse `core.memberships`: it represents patient plans/packages, not staff authorization. Map source membership active/role state to staff active/role. Do not merge identities or attach existing staff merely because email matches; existing-clinic access needs an explicit verified invitation/admin linkage.

Onboarding must supply a valid `clinic_type`, create tenant plus owner staff plus approved feature entitlements atomically, and preserve the source double-submit protections. Map workspace callback phone deliberately to an appropriate location or documented tenant setting. New accounts must not automatically receive all features or a signed BAA. Preserve old workspace IDs where feasible for existing users, otherwise use an explicit durable ID map.

Build RequestContext from a valid session and active staff membership. Treat a tenant cookie/header only as a selection hint, never proof of access; reject forged roles/actor IDs. Initially keep one-workspace onboarding behavior unless deliberately expanding it. Maintain `/api/v1/auth/me` for session/onboarding and `/me` for platform feature/nav data, sharing the same verified identity policy.

### Database and transaction ownership

Parent feature sessions use `session.begin()` and a transaction-local RLS setting. Source auth repositories/services call `commit()` themselves. Do not copy those commits into tenant-scoped services: ending a transaction can lose the tenant setting and break atomicity. Let parent tenant/provisioning units of work own commit/rollback; use `flush()` within them. Preserve explicitly separate auth transactions where needed: claiming an OAuth transaction must remain durable before exchanging a one-use authorization code, and rate-limit updates must survive appropriate failure paths.

Use the parent SQLAlchemy Base, Python 3.12, one uv workspace and one migration head. Keep the parent's psycopg driver unless a measured reason requires another; source asyncpg assumptions and tests must be adapted. A separate `0001_auth` migration and independent Alembic version table are not the merged migration history.

All voice tables use `TenantMixin` and RLS. Ensure references to agent versions, numbers and shared clinic entities belong to the same tenant; ordinary UUID foreign keys alone do not prove that. Use composite tenant-aware constraints and/or explicit validation. Parent booking currently checks the patient but does not fully validate every optional related ID or deduplicate retries; harden those cases before voice tools retry bookings.

Proposed first voice tables: agents, immutable agent versions, phone numbers, calls, call events/transcript turns, tools, variables and tool executions. These are new backend models inferred from the UI, not existing source models. Start with agents/versions/numbers/calls; expand tools/variables only as their contracts are implemented. Recordings belong in object storage with authorized references, not committed media files.

### HTTP and frontend contracts

Keep the existing feature API prefix `/features/voice_receptionist`. Preserve `/api/v1/auth/*` for Google callback compatibility and adapt `/api/v1/workspaces` to canonical tenant provisioning if retaining that endpoint during transition. Add same-origin proxy routes for existing platform endpoints or an explicit equivalent gateway mapping; forwarding only `/api/v1/*` is insufficient for `/me`, `/appointments`, `/imports`, and `/features/*`. Preserve existing client contracts while migrating auth.

Forward session cookies on server-side API calls, send credentials for browser calls, and attach CSRF tokens plus valid origin policy to authenticated writes. Update `@clinic/api-client` to stop synthesizing trusted identity from dev headers. Regenerate types after endpoint changes. Retain source PKCE/state/nonce/browser binding, session expiry/revocation and no-store behavior. Audit every write endpoint, not just the imported auth routes.

Use `/voice-receptionist` as the canonical voice UI root; `/` remains the platform overview. Change OAuth success redirects from `/dashboard` to the platform landing page. Optional legacy dashboard redirects must be explicit. Retain a visible sample-data mode while mock voice services remain; login is real but a simulated test call is still simulated. Demo state must be isolated by verified user and tenant and cleared on logout/account change.

The parent lockfile records Next 16.4.0 / React 19.3.0; source manifests request Next ^16.0.0 / React ^19.2.0. These are local manifest/lock observations, not independently verified available releases. Reconcile against parent installed versions rather than importing the npm lock. Add needed lucide/Playwright/lint dependencies deliberately. Source pytest fixtures use function loops while the parent uses session loops: adapt engine/fixture scopes before combining tests.

### Runtime and cross-feature actions

Do not process continuous audio inside BullMQ or run it in the normal API process. Keep live transport/pipeline code in `apps/voice-agent`; keep control-plane lifecycle and authorization in the voice feature; keep provider/client integrations in the appropriate integration adapters. Define a short-lived service credential bound to tenant, call and published agent version. Runtime requests must validate that binding and entitlement without trusting a caller-supplied tenant ID.

Provider webhooks and media callbacks need their own signature/service-auth route policy: normal cookie-gated feature endpoints cannot simply receive unauthenticated carrier callbacks. Authenticate the provider, resolve the configured phone-number-to-tenant mapping, then check entitlement and create a scoped session. No tenant identity is accepted from an arbitrary webhook payload.

Register asynchronous summaries, recording processing and retention as feature jobs. Use idempotent call/provider event IDs because queue/event delivery can repeat. Define agreed `voice.call.started` and `voice.call.completed` events carrying IDs rather than full transcripts. Book through the canonical platform booking capability so `appointment.booked` is emitted; SMS/email uses engagement. The `phi_sensitive` flag is metadata today, not an implemented consent/BAA gate: add explicit enforcement before real recording or patient calls.

## 6. When to copy: phased execution and gates

Estimates below are engineering effort ranges for one engineer familiar with both repos, not promised calendar deadlines. Migrate the implemented auth/UI first. Live voice is separate work.

| Phase | Work and copy timing | Exit gate | Indicative effort |
| --- | --- | --- | --- |
| 0. Baseline | Install parent dependencies; resolve installed Turbo docs; run baseline checks; record source commit and inventory; decide whether existing DB data needs migration | Baseline failures documented; verified snapshot; tenancy/routes agreed | 0.5 day |
| 1. Shared DB/auth | Convert and copy auth/user code into core/db; add membership linkage, auth access role and parent migration; add consolidated settings | Fresh DB migrates; one head; auth state/nonce/session/CSRF tests pass; no identity merge by email | 1-2 days |
| 2. Platform integration | Mount auth/onboarding; replace RequestContext and API client dev identity; split auth/platform layouts; port login/onboarding | Real Google login, owner onboarding, reload/logout work; other clinic features work under sessions; tenant isolation passes | 1-2 days |
| 3. Voice frontend | Copy mapped voice components/routes/assets; scope CSS, rewrite links, gate layout; retain sample adapters | Every voice route and direct refresh works; entitlement denial; existing UI unchanged in behavior; responsive tests pass | 1-2 days |
| 4. Real voice control plane | Build agent/version/number/call schemas and APIs; replace mocks progressively | Two tenants isolated; publish snapshots immutable; CRUD/call persistence and generated client tests pass | 2-4 days |
| 5. Live runtime | Create runtime workspace; select/benchmark transport and providers; implement authenticated calls and persistence | Real inbound call, transcript, recording consent, failure handling and retries tested | Estimate after runtime scope/benchmark |
| 6. Deployment | Consolidate production gateway/runtime config, secrets, backups, observability and runbook | HTTPS Google flow and real call smoke test pass; rollback rehearsed | Estimate after hosting scope |

The existing source migration, auth and dashboard code can be relocated and integrated in roughly 3.5-6.5 engineering days under these assumptions. That estimate excludes new voice APIs, live runtime, external provider setup, existing-data migration and production hardening. The source's 16 October target is a historical plan, not evidence that the combined remaining work fits that deadline.

If existing users/workspaces must be retained, add a separate data migration before switching traffic: export identity/workspace/membership records, map tenant/staff IDs, import into the new schema, validate counts/ownership, and reconcile staff records. Prefer requiring fresh sign-in after cutover rather than moving active session/OAuth material. Retain the old database backup; do not run parent migrations against the source database as a shortcut.

## 7. Validation and completion criteria

First establish the parent's documented baseline: migration heads/model consistency, RLS coverage, Python tests/lint/format, import boundaries, generated API freshness, TypeScript and production build. No installed `turbo` package was resolvable in the parent during this analysis. Read its bundled `docs/README.md` and relevant task/workspace/env docs after installation and before modifying Turbo commands/configuration; no Turbo configuration has been changed here.

Migration verification must include:

- Authentication: mocked signed Google claims plus real local Google acceptance; expired/replayed state, browser mismatch, disabled user, logout replay, CSRF and production cookie behavior.
- Authorization: two users/two tenants; forged selected tenant and role headers; removed membership; absent/expired voice entitlement; no cross-tenant agent/call/tool access or related-object references.
- Transactions: onboarding double submit, failed provisioning rollback, OAuth claim durability, RLS context maintained throughout feature writes.
- Regression: reactivation, blueprints, imports, appointments and worker delivery still work; booking emits its existing event once for a deduplicated operation.
- Frontend: login renders without a tenant; all moved URLs preserve behavior; voice sample notice remains; CSS does not alter existing feature screens; keyboard and mobile journeys work.
- Contracts/tooling: one uv/pnpm lock pair, one migration head, no independent source app DB Base, no forbidden app-to-feature imports, generated API types current, adapted Playwright test-only provider.
- Runtime release later: provider signatures, service credential scope/expiry, tenant routing, consent, duplicate/out-of-order events, transport/provider failure and real call persistence.

Use separate reviewable changes for DB/auth, platform session integration, voice UI, real voice APIs, and runtime/deployment. Each phase keeps the previous source checkout available. For code rollback, revert the relevant change; database rollback requires a tested compatible migration or restore procedure, not an assumption that reverting Git restores the database.

## 8. Next implementation step

Start with phase 0 and shared auth/tenancy conversion, then port the voice UI after the session and layout gates pass. Keep `packages/features/voice-receptionist` as the voice control-plane home. Create the live agent app only when there is runtime code to put there. This preserves the source implementation while making it part of the parent's existing architecture.
