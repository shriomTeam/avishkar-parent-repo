# Architecture

The Always-On Clinic is **one product with sellable components**, not ten
separate apps. Teams work in parallel inside one Turborepo, on one database
schema, behind one feature contract.

```
apps/
  web/                 Next.js: one shell, shows only what the tenant bought
  api/                 FastAPI: mounts each installed feature at /features/<key>
  worker/              BullMQ worker: feature jobs, event fan-out, outbox relay, sends
packages/
  db/                  ALL tables (SQLAlchemy) + ONE Alembic migration stream
  core/                tenant sessions (RLS), feature contract, entitlements, events, audit, queue
  integrations/        client data in: CSV / Excel / client DB / EMR API -> canonical core.*
  engagement/          shared SMS/email sequence engine + consent/quiet-hours rules
  features/<name>/     one package per sellable component, owned by one team
  ui/                  shared React components (one design across features)
  api-client/          TypeScript types generated from the FastAPI OpenAPI spec
```

## Decisions

### 1. Sell features through entitlements, not code distribution
Clinics use a hosted multi-tenant SaaS. What a clinic bought is a row in
`core.tenant_features`. The same key is used everywhere:

| Sellable component | Feature key | Package |
|---|---|---|
| Dormant Revenue Finder | `reactivation` | `features/reactivation` |
| Patient Blueprints | `blueprints` | `features/blueprints` |
| The 60-Second Response System | `lead_response` | `features/lead-response` |
| The 5-Star Machine | `reviews` | `features/reviews` |
| The Front Desk That Never Sleeps | `voice_receptionist` | `features/voice-receptionist` |
| The Chart-While-You-Talk System | `scribe` | `features/scribe` |
| The Command Center | `command_center` | `features/command-center` |
| Before/After Photo Pipeline | `photos` | `features/photos` |

It is enforced in three places: API (`require_feature` on every feature
router → 403), worker (jobs and event handlers skip tenants without the
feature), web (`/me` returns only enabled nav; feature pages call
`requireFeature`). Automatic 14-day onboarding trials are currently paused while
billing is not implemented. New workspaces are active with non-expiring starter
entitlements; explicit entitlement expiry and suspension are still enforced.
See [workspace access policy](WORKSPACE_ACCESS_POLICY.md) for existing-trial
migration behavior and requirements before re-enabling billing/trials.

If a deployment must physically exclude a feature's code (e.g. a dedicated
install), don't install that feature's package: the API and worker discover
features through the `clinic.features` entry point, so nothing else changes.
`turbo prune` does the same for the JS side.

### 2. One database schema, namespaced per feature
- Shared entities (patients, appointments, providers, services, transactions,
  leads, memberships, care plans, inventory lots, consents) live in `core` and
  are defined once.
- Each feature gets its own Postgres schema (`reactivation.*`, `voice.*`, ...)
  for tables only it writes. All models live in `packages/db`, so a table can't
  be defined twice, and there is one migration stream (`check-heads` fails CI if
  two teams' migrations fork).
- Every tenant gets every table. An unused feature's tables are just empty.
- Enum-like columns are strings validated in Python (adding a value needs no
  migration). Client-specific extra columns go into `attributes` JSONB.

### 3. Tenant isolation in Postgres, not just in code
Global Google identities and sessions live in `auth.*`, using a restricted
`clinic_auth` connection. `core.staff.user_id` links verified users to clinics.
A session plus active staff membership produces the platform RequestContext;
tenant selection never grants access. Onboarding and membership discovery use
narrow system-session operations, followed by normal tenant RLS sessions.
The imported voice UI lives under `/voice-receptionist`, with scoped styles and
sample service adapters. See [the voice guide](voice-receptionist/README.md).

Every table with `tenant_id` has row-level security. The API and worker connect
as `clinic_app` (not the table owner) and every transaction sets
`app.tenant_id`, so a query that forgets `WHERE tenant_id = ...` still can't
see another clinic's patients. A test fails if a new tenant table lacks RLS.
`clinic_system` (BYPASSRLS) is used only for cross-tenant scans in the worker.

### 4. Features talk through core tables and events, never imports
`import-linter` enforces: features don't import each other; apps don't import
features (they discover them); layers go apps → features → integrations /
engagement → core → db. Cross-feature reactions use the transactional outbox:
`emit(session, "appointment.booked", {...})` in the same transaction, the worker
relays it to BullMQ and fans it out to every enabled feature's handlers.
Example: the voice agent books → reactivation attributes the booking → the
engagement engine stops that patient's sequences → reviews (later) asks for a
review after `appointment.completed`.

### 5. Client data: map, don't migrate
Any client source becomes rows for one entity type, which pass through
`staging.raw_records` (kept for audit and re-processing), a per-client
**mapping** (data in `staging.source_mappings`, suggested automatically from
the headers), validation, and an idempotent upsert into `core.*` via
`core.external_refs`. A new EMR means a new mapping or connector, never a
schema migration. Bad rows are reported with their reason; they don't fail the
batch. Imports are blocked until the tenant's BAA is signed.

### 6. One outreach engine for everything that texts or emails
Reactivation, lead follow-up and review requests declare `SequenceDef`s; the
engagement engine sends them and handles consent (explicit SMS opt-in by
default), quiet hours (8am–9pm clinic time), STOP keywords, and stopping when
the person books or replies. Compliance is implemented once.

### 7. Typed contract between Python and TypeScript
FastAPI's OpenAPI spec generates `@clinic/api-client` types. CI fails if the
generated types are stale, so a backend change that breaks the web app is a
type error in the PR.

## Compliance notes
- `voice_receptionist`, `scribe` and `photos` are flagged `phi_sensitive`;
  call/visit recording consent rules depend on `core.locations.state`.
- `ops.audit_log` is append-only for the app role (UPDATE/DELETE revoked).
- Before production: production HTTPS acceptance for Google auth,
  field-level encryption for clinical notes, secrets management, backups,
  and a BAA with every vendor in the PHI path (DB host, Twilio, speech-to-text, LLM).
