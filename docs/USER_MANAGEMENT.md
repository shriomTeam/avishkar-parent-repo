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
Ownership transfer is intentionally outside this interface. Removed memberships
stay inactive until a fresh re-invitation is accepted. Resend rotates the token;
revoke invalidates it.
The UI lists up to 100 pending, unexpired invitations with provider submission
status. Accepted, revoked and expired invitations remain stored for history and
auditing but are excluded from this list; accepted people appear in Workspace
members. Refresh invitations also refreshes the member list.

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

## Roles and access permissions

This table describes the current backend policy, not planned capabilities. Permissions
apply only to the selected workspace with an active membership. Feature access also
requires that product to be enabled for the workspace; an Owner role does not bypass
entitlements. A role in one workspace grants no authority in another.

| Capability | Owner (`owner`) | Office Manager (`office_manager`) | Front Desk (`front_desk`) | Provider (`provider`) | Consultant (`consultant`) |
| --- | --- | --- | --- | --- | --- |
| Sign in, view own account, sign out | Yes | Yes | Yes | Yes | Yes |
| Switch between workspaces where actively enrolled | Yes | Yes | Yes | Yes | Yes |
| Read workspace details, including clinic contact information | Yes | Yes | Yes | Yes | Yes |
| Edit workspace/clinic settings | Yes | Yes | No | No | No |
| View workspace member directory and pending invitations | Yes | Yes | No | No | No |
| View workspace audit log | Yes | Yes | No | No | No |
| Invite Front Desk, Provider or Consultant | Yes | Yes | No | No | No |
| Invite an Office Manager | Yes | No | No | No | No |
| Change roles, remove or re-invite Front Desk, Provider or Consultant | Yes, except self | Yes, except self | No | No | No |
| Change role, remove or re-invite an Office Manager | Yes | No | No | No | No |
| Grant Owner, change/remove an Owner, or change own membership | No | No | No | No | No |
| Read Voice Receptionist calls, transcripts and saved recordings | Yes | Yes | Yes | No | No |
| Read/manage voice agents, tools and variables; run test/browser calls | Yes | Yes | No | No | No |
| Read Dormant patients run status, type totals, data status and schedule | Yes | Yes | Yes | No | No |
| Start reactivation runs, analyse CSVs or edit reactivation settings | Yes | Yes | No | No | No |
| Read patient-level reactivation lists, detailed summary and report endpoints | Yes | Yes | No | No | No |
| Import patient/appointment data | Yes | Yes | No | No | No |
| Access Patient Blueprints and other enabled feature routers | Yes | Yes | No | No | No |

### Role-specific limits

- **Owner:** manages workspace settings and all non-owner roles. Ownership transfer
  is not implemented through invitations or member management. Owners cannot edit
  their own membership or another Owner's membership through these endpoints.
- **Office Manager:** manages workspace settings and the three member roles (Front
  Desk, Provider and Consultant). Cannot manage an Owner or another Office Manager,
  promote someone to Office Manager, or demote a manager to bypass that restriction.
- **Front Desk:** has the read access listed above for Voice Receptionist and Dormant
  patients. Cannot configure voice agents, tools or variables, start test calls,
  access patient-level reactivation reports, import data, edit workspace details,
  view the member directory/audit log or manage invitations.
- **Provider:** can use account/workspace basics but currently has no product feature
  access. The role name does not grant clinical records or patient access. Further
  provider capabilities need an explicit permission policy and implementation.
- **Consultant:** has the same current account/workspace-only access as Provider.
  No reporting, patient data or administrative access is implied by this role.

### Invitation and removal restrictions

Owners and Office Managers can see the workspace's pending invitation list, but
resend/revoke actions require authority over the invitation's target role. For
example, an Office Manager cannot resend or revoke an Office Manager invitation.
Acceptance rechecks the inviter's current authority; an old link cannot retain
permissions the inviter has since lost. Issuance/resend also depends on the
invitation feature flag and configured delivery settings.

Re-inviting an inactive member requires authority over both their previous role
and the new invitation role. An Office Manager cannot restore a former Office
Manager by selecting Front Desk. Re-invitation is available only for eligible
members linked to a user; the original Google identity must accept. Pending
invitations do not grant access before acceptance.

Removed members lose access to that workspace, including its settings and feature
APIs, while retaining any separate active memberships elsewhere. Nobody can view
another workspace's records by changing a URL or tenant header. The backend enforces
these restrictions; hiding a navigation item is not the authorization boundary.

### Policy implementation references

- `packages/core/src/clinic_core/tenancy/permissions.py`: feature eligibility and
  grantable roles.
- `packages/core/src/clinic_core/tenancy/management.py`: workspace settings,
  membership and manager checks.
- `packages/core/src/clinic_core/tenancy/invitations.py`: invitation acceptance,
  role changes, removal and restoration restrictions.
- `apps/api/src/clinic_api/routers/onboarding.py` and `invitations.py`: settings,
  member directory, audit and invitation endpoints.
- `apps/api/src/clinic_api/main.py`: import permissions and feature entitlement gates.
- Voice feature `inbound/router.py`, `tools/router.py`, `variables/router.py`, and
  reactivation feature `api/roles.py`, `api/settings.py`, `api/results.py`:
  operation-specific manager/viewer restrictions.

## Re-invite a removed member

1. Open **Settings → User management** and use the **Inactive** status filter if needed.
2. Click **Re-invite <name>** on the removed member. Their email is prefilled and
   read-only; select the role they should have when they return.
3. Send the invitation. The member stays inactive until they open the fresh link,
   sign in with the original Google account and accept.

Acceptance reactivates the same membership ID in the same workspace and uses the
new invitation's role; it does not create a duplicate member or restore old roles
implicitly. A different Google identity cannot take over an inactive membership,
even if it now owns the same email address. Owners can re-invite removed office
managers; office managers cannot bypass that restriction by choosing a lower role.
Owner memberships and inactive imported records without a linked user remain
protected. Duplicate pending invitations use the existing Resend/Revoke actions.
Removing access also revokes outstanding invitations to that member, so old
pending links cannot restore access. Restoration emits a `member.restored` audit
record. No database migration is needed for this flow.

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

## Audit log: current implementation and limits

Workspace audit events are persisted in PostgreSQL `ops.audit_log`, separate from
application authentication log messages. There is no application-defined row/count
quota, automatic expiry, retention job or archive policy. Actual capacity depends
on database disk, indexes, backups and infrastructure limits; this is not unlimited
storage. Deleting a tenant cascades deletion of its audit rows.

Each row stores a bigint identity, workspace ID, actor type/ID, action, optional
entity type/UUID, JSON details and timestamp. Current indexing includes the tenant
ID, primary key and a composite tenant/time/ID index for history browsing. Run
`pnpm db:migrate` to apply the new concurrent index migration.

**Implemented:**

- Owner/Office Manager access only, with server-side workspace membership checks.
- 50 events per page, ordered newest first by timestamp and ID, with Previous/Next
  navigation and matching result counts. All stored history is accessible.
- From/To dates (inclusive calendar days in the workspace timezone), Actor and Event
  filters combine together. Apply filters resets pagination; Clear filters restores
  the full history. Actor choices include historical IDs and system actors.
- Download CSV exports **all** matching rows, independently of the current page.
  With no filters applied it exports the entire workspace history. Exports include
  event/actor/entity IDs and UTC timestamps; arbitrary JSON details are excluded.
  The server reads batches of 500 rows and excludes new events added after the
  export starts. Spreadsheet formula prefixes in text are escaped. Downloads use
  the same manager/workspace authorization as the table and are not cached.
- The Settings table displays event, actor and workspace-local time. Actor names
  resolve from workspace staff records (including inactive members), supporting
  both current member IDs and legacy account IDs. Unresolvable staff actors show
  “Unknown member”; other actor types keep their type label. Original IDs remain
  available in CSV exports. Names are not historical snapshots.
- Workspace updates, invitation creation/resend/revoke/acceptance, member role
  changes/removal/restoration are recorded. Workspace updates record field names,
  but not before/after values; member role changes do not record old/new roles.
- Voice records agent/tool/variable changes, tool tests, test-call starts,
  transcript views and recording playback. Reactivation explicitly records run
  requests, CSV analysis, settings changes and selected sensitive report reads.
  This is explicit call-site coverage, not automatic auditing of every endpoint.
- The normal tenant application database role cannot update/delete audit rows.
  Administrative/provisioning roles remain privileged; this is not a tamper-proof
  or cryptographically verified audit trail.

**Not implemented yet:** structured entity/detail display, comprehensive before/after change history, stable historical
actor labels, archival/retention management, or comprehensive failed/denied-action
coverage. Login/logout events are application logger messages, not entries in this
workspace audit table. Their retention depends on the logging deployment.

Further improvements include safe event metadata (including old/new roles) and
stable historical actor labels. Choose an explicit retention/archive policy before
introducing automatic deletion. Avoid putting credentials, invitation tokens or
unnecessary patient information into event details.

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
