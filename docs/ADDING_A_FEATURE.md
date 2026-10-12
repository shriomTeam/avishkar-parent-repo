# Building a feature (team guide)

Your stub already exists in `packages/features/<name>/`. `reactivation` is the
complete reference: copy its shape.

## 1. Tables
Add `packages/db/src/clinic_db/models/<schema>.py` (schema name is in
`clinic_db.base.FEATURE_SCHEMAS`), import it in `models/__init__.py`, then:

```bash
pnpm db:revision "add lead_response tables"   # autogenerates from the models
```

Edit the generated file: after each `op.create_table(...)` for a table with
`tenant_id`, add `enable_tenant_rls(op, "<schema>.<table>")`. The schema
already exists with grants. Then `pnpm db:migrate`.

Rules:
- Reference shared data (`core.patients`, `core.appointments`, ...) by foreign
  key. Never copy it into your schema.
- Need a new shared column or entity? That's a `core` change: open a PR for the
  platform team rather than adding it to your schema.
- Every tenant-scoped table uses `TenantMixin`.

## 2. Backend
Everything goes through `feature.py`:

```python
feature = Feature(
    key="lead_response",
    name="The 60-Second Response System",
    description="...",
    router=router,  # mounted at /features/lead_response, entitlement-gated
    jobs={"sync_ads": sync_ads},  # enqueue("lead_response.sync_ads", tenant_id)
    schedules=[Schedule(job="sync_ads", every_seconds=300)],
    event_handlers={LEAD_CREATED: [on_lead_created]},  # only runs for tenants that have the feature
    sequences=[FOLLOW_UP],  # SMS/email via clinic_engagement
    nav=[NavItem(label="Leads", path="/lead-response")],
)
```

- In routes, use `Depends(get_session)`: it's already tenant-scoped (RLS).
- Handlers get `JobContext(tenant_id, session)`. Make them **idempotent**,
  because a failed event is retried.
- To affect another feature, `emit()` an event (add its type to
  `clinic_core/events.py`). Don't import other features; CI blocks it.
- Book appointments via the platform's `/appointments` endpoint so
  `appointment.booked` is always emitted.
- Never send SMS/email directly. Declare a `SequenceDef` and `enroll()`.

## 3. Web
Pages go in `apps/web/app/(platform)/(features)/<path>/`. Start each page with
`await requireFeature("<key>")`, use `@clinic/ui` components, and call the API
through the typed client (`pnpm api-client:generate` after backend changes).

## 4. Tests
Put tests next to your package (`tests/`), with a fresh tenant per test from
`clinic_core.testing.create_test_tenant` (see `features/reactivation/tests`). Run only your slice:

```bash
pnpm turbo run test lint --filter=@clinic/feature-lead-response
```
