# Workspace user management and transactional email

## Behavior

Owners and office managers open their profile menu → Settings → User management.
Invitations are emailed to one recipient, expire after the configured lifetime
(default 72 hours), and require explicit acceptance with the matching Google
account. Acceptance inserts membership in the existing workspace; it never calls
workspace creation or grants another trial. Users with multiple memberships get
a workspace selector. The selected workspace is stored on the server-side session.

An Owner can invite Office managers, Front desk, Providers and Consultants. An
Office manager can invite/manage Front desk, Providers and Consultants. Nobody
can grant Owner, remove/demote an Owner, or change their own membership here.
Ownership transfer is intentionally outside this interface. Disabled memberships
are not silently reactivated. Resend rotates the token; revoke invalidates it.
The UI lists the latest 100 invitations with provider submission status.

Front desk can read voice calls/transcripts/recordings and reactivation summaries
in their workspace. Agent configuration, tools, variables, test calls, imports,
workspace editing and member management require Owner/Office manager. Provider
and Consultant currently get no sellable feature access until an explicit policy
is added. Entitlements are still required even when a role permits a feature.
Patient-level reactivation access retains that feature's manager restrictions.

Role/removal checks happen in the backend, on every request. UUIDs and a supplied
tenant header do not authorize access. Voice browser calls bind to the session
that created their ticket, revalidate membership every five seconds and before
running a configured tool, and fail closed when validation is unavailable.
Client session refresh redirects on role/workspace changes, rather than retaining
an outdated management interface. There is no claim of a completed penetration
test or a guarantee against every future security defect.

## Email configuration

```dotenv
INVITATIONS_ENABLED=true
EMAIL_PROVIDER=sendgrid
SENDGRID_API_KEY=<server secret>
EMAIL_FROM_ADDRESS=abhinav.chaudhary@avishkar.app
EMAIL_FROM_NAME=Avishkar AI
EMAIL_REPLY_TO=abhinav.chaudhary@avishkar.app
EMAIL_PAYLOAD_ENCRYPTION_KEY=<server secret, valid Fernet key>
INVITATION_TTL_HOURS=72
```

The sender has been verified through Single Sender Verification according to the
user-provided screenshot. Domain authentication and live delivery are not verified
by automated tests. Use domain authentication for production deliverability.

Generate the encryption key with:

```sh
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Keep it private and stable across API and worker restarts. It is separate from
the SendGrid API key. For rotation, configure comma-separated old keys through
`EMAIL_OLD_PAYLOAD_KEYS` on both runtimes until existing encrypted deliveries have
drained. Active encryption uses the new key; old keys only permit decryption.
Changing the sender later only changes configuration.

Use local `PUBLIC_APP_ORIGIN=http://localhost:3000`. Production origin is:

```text
https://prod-avishkar-web-287171356403.us-east1.run.app
```

Do not append `/voice-receptionist` to the origin. Invitation links target `/invite`
at the application root. Keep the Google callback consistent with that origin.
Restart the API and delivery worker after changing environment configuration.

## Running delivery

Migrate before running the new API or worker:

```sh
pnpm db:migrate
```

With `EMAIL_PROVIDER=sendgrid`, invitation creation, resend and mailbox verification
first commit their database transaction, then await `deliver_email(delivery.id,
settings)` inside the active API request. It claims only that email using the same
durable lease as the worker and attempts SendGrid immediately. There is no
scheduler wait on the normal path. The attempt is bounded to 20 seconds; failed or
interrupted attempts remain recoverable. A provider error does not undo an already
committed invitation or falsely report that invitation creation failed. This is
awaited before the response so Cloud Run does not need idle CPU after the request.
Console/test providers retain queued records for explicit captured dispatch and
never send real email through this path.

The existing `clinic-worker` recovers queued records and retries due failures.
For local testing or a deployment that only needs email recovery, run the isolated dispatcher:

```sh
uv run python -m clinic_engagement.email.worker
```

This dispatcher only processes transactional email, not patient sequences or SMS.
For a scheduler/job execution, pass `--once`; each invocation drains up to 20 due
records. The continuous process polls every ten seconds. A healthy SendGrid initial
submission works even without a dispatcher, but interrupted requests and retries
need this recovery process. Creating an invitation never pretends inbox delivery
has been confirmed.

The SendGrid transport uses the fixed v3 Mail Send endpoint and server credentials,
disables open/click tracking, and never logs the body, token or recipient. A 202
is provider acceptance, **not confirmed delivery**. No delivery webhooks are
implemented in this release, so no Delivered status is shown.

Delivery is at least once: leases, bounded retries, deduplication and state checks
reduce duplicate submissions, but an HTTP timeout after provider acceptance can
still produce a duplicate email. Acceptance cannot grant a duplicate membership.
Retryable failures retain encrypted payloads; terminal failures/provider acceptance
clear them. Failed invitations can be resent with a new token after cooldown.

## Reuse from any backend feature

```python
from clinic_engagement.email import deliver_email, enqueue_email
from clinic_engagement.email.template import invitation

delivery = await enqueue_email(
    db,
    tenant_id=workspace.id,
    to=[recipient_email],
    template=invitation(
        workspace=workspace.name,
        inviter=actor.name,
        role=role,
        email=recipient_email,
        url=server_generated_url,
        hours=72,
    ),
    deduplication_key=business_operation_key,
    settings=settings,
)
```

Call this inside the same transaction as the business operation. After the
transaction context has exited successfully (committed), optionally call
`await deliver_email(delivery.id, settings)` before returning the API response for
immediate submission. Never call it inside the transaction: another connection
must be able to see the saved record. Queue-only background operations can leave
submission to the worker. Future templates
live in `packages/engagement/src/clinic_engagement/email/template/` and return an
`EmailContent(subject, text, html)`. Export the factory, import it and pass it to
the same `enqueue_email` function. The template files ship with the package.
Queue recipients individually to avoid disclosing addresses to each other.
Only trusted backend callers choose recipients and authorize the operation; no
public generic-send endpoint exists. Core domain logic never imports engagement.

`send_email(to=..., template=..., settings=...)` is the immediate transport used by
the worker; it lives in `email/sendgrid.py` and has no invitation/database logic.
SMS selection remains independent. The existing messaging adapter can delegate
email to this transport without replacing the SMS provider or consent engine.

## Storage and security

- `core.workspace_invitations`: tenant, recipient, role, inviter, token hash,
  generation, expiry and accepted/revoked state. One pending recipient per tenant.
- `auth.invitation_contexts`: opaque browser-bound invitation continuation and
  optional short-lived verification challenge. No raw invitation token is stored.
- `ops.email_deliveries`: encrypted recipient/content/URL, scoped deduplication
  key, attempt lease, error code and provider submission metadata. Ciphertext is
  bound to its delivery/tenant identity. Redis/outbox payloads only contain ids.
- `auth.auth_sessions.active_workspace_id`: selected workspace, reauthorized
  against current memberships. A narrow system-role grant lets acceptance update
  this column in the same transaction as membership creation.

Invitation URLs use a fragment, removed before exchanging for an HttpOnly context
cookie. Google login binds that context to OAuth state. GET/scanner requests do
not accept invitations. Acceptance requires CSRF/Origin, a recent login, current
inviter authority and a matching email; non-authoritative Google email claims also
need a fresh mailbox code. The invitation page has a nonce-based script CSP,
no third-party content, no framing, and a no-referrer policy.

The production feature flag defaults off. Revocation remains available if issuance
is disabled. Existing members are not removed when invitations are disabled.

## Production rollout

Terraform creates secret **containers**, never the secret values. Provision current
versions of `${name}-sendgrid-api-key` and `${name}-email-payload-key` outside
Terraform through the secret workflow. Do not put key values into tfvars or state.
Set `invitations_enabled=true`, `email_from_address`, optional `email_reply_to` and
`email_from_name` only after those versions and the verified sender are ready.

The optional private `${name}-email` Cloud Run Job uses the current API image and
is invoked every minute by Cloud Scheduler with a job-scoped invoker identity.
It is the recovery/retry fallback; new invitations are attempted immediately in
the API request and do not wait for this schedule. The deploy workflow updates its image when it is provisioned. Terraform applies
and release deployment are not performed by local implementation/testing.

Run the migration before the API release. Verify queued → provider-accepted with
an approved recipient and check spam/bounce handling manually before a broad
rollout. Configure monitoring for failed/old queued deliveries. Until signed
SendGrid delivery webhooks are added, investigate actual delivery in SendGrid.

## Validation

Routine pytest disables inherited live email configuration in root `conftest.py`.
Provider tests inject a fake key and mock HTTP transport. Browser tests use the
separate test-only API entry point and a captured-email dispatcher; its helper
routes do not exist on the production app.

Use Node 24 (matching CI) for repository tests; the existing reactivation workbook
test runs a TypeScript file directly. Use a disposable migrated PostgreSQL database
for integration tests and never point TEST_* URLs at production.

Covered cases include original-workspace join, an existing user's second workspace,
wrong account, optional mailbox proof, role escalation, cross-workspace selection,
resend/revoke, duplicate acceptance, removal, encrypted payloads, provider errors
and durable retries. Shared Settings/email/invitations have no imports from Voice
Receptionist and remain available when that feature package is removed.

See the [PR validation report](USER_MANAGEMENT_VALIDATION.md) for test coverage, dependency findings and release gates.
