# Workspace invitations and reusable transactional email

Status: implemented on `user/management`. This document records the original design;
see [USER_MANAGEMENT.md](USER_MANAGEMENT.md) for current behavior, setup and rollout.
Branch: `user/management`. Existing homepage and shared Settings changes were
committed as `b1bafbe` before this plan was written.

## 1. Outcome and scope

An authorized workspace manager invites an email address with an allowed role.
The recipient opens the invitation, signs in with the matching Google account,
confirms acceptance, and becomes a member of **that existing workspace**. No
workspace is created by acceptance. Existing users keep their global identity
and any other workspace memberships; permissions never carry between workspaces.

Deliver invitations through SendGrid using a shared, server-side email service
and exported templates under a `template/` folder. Future notifications reuse
that service without copying provider code. No live email is sent by this plan.

Initial scope includes invitations, pending invitation listing, resend, revoke,
acceptance, active workspace switching, and the authorization needed to make
those safe. Member role changes/removal use the same policy and invariants, but
can land after invitation acceptance. Ownership transfer is a separate workflow;
there is no invitation that grants Owner.

There is no credible promise of zero security flaws. Release confidence comes
from explicit invariants, transaction boundaries, negative tests, and review.

## 2. Current repository facts

- Global users and Google identities are in `auth.users` / `auth.auth_identities`.
  Identity is keyed by provider + Google `sub`, not email.
- Membership is `core.staff`: `tenant_id`, `user_id`, `email`, `role`, `active`.
  There are existing uniqueness constraints on tenant/user and tenant/email.
- Roles are `owner`, `office_manager`, `front_desk`, `provider`, `consultant`.
  Do not add ambiguous Admin/Staff aliases as new authorization roles.
- Google login verifies signed claims, issuer, audience, expiry, nonce, PKCE and
  `email_verified`. Keep those checks.
- `/auth/me` and the callback currently default to the first membership. Next.js
  can reorder memberships using `clinic_tenant`, but client session refresh and
  backend defaults are not one authoritative active-workspace selection.
- Workspace creation is an explicit onboarding operation. Invitation acceptance
  must never call `create_workspace()` or grant another preview trial.
- Tenant RLS, current membership checks, feature entitlements and some manager
  checks already exist. However, nav filtering is not endpoint authorization:
  voice call/recording reads, for example, need an explicit permission decision
  before additional roles are onboarded. This plan is not a claim of a complete
  security audit of every feature.
- `clinic_engagement` currently has Console and Twilio messaging adapters; its
  Twilio email method is unconfigured. The console adapter logs bodies, which is
  unsuitable for invitation tokens.
- `apps/worker` is Python/BullMQ, with PostgreSQL outbox relay and platform event
  handlers. Reuse it; do not start another application/service.
- Dependency direction is apps → features → engagement/integrations → core → db.
  Core must not import engagement to send an invitation.
- `SENDGRID_API_KEY` exists in local `.env`. Presence does not establish key
  validity, sender verification, delivery readiness or production configuration.
  No verified sender/reply-to variables were found in the inspected environment.

## 3. Product and security defaults

These are proposed defaults, configurable where appropriate:

| Action | Owner | Office manager | Other roles |
|---|---|---|---|
| View members and pending invitations | Yes | Yes | No |
| Invite/resend/revoke Front desk, Provider or Consultant | Yes | Yes | No |
| Invite/resend/revoke Office manager | Yes | No | No |
| Invite Owner | No; separate ownership transfer | No | No |
| Change ordinary member roles/remove members | Yes | Only delegated non-manager members | No |
| Change/remove Owner or Office manager | Owner only, with owner safeguards | No | No |
| Edit workspace information/view management audit | Yes | Yes | No |
| Accept invitation | Matching authenticated recipient only, regardless of current role elsewhere |

Default invited role: Front desk. Role and recipient cannot be edited on resend;
revoke and issue a new invitation for either change. No self-promotion through a
request body, stale dropdown, forged header or another workspace's role.

Feature access requires all applicable checks:

`active user + active membership + selected workspace + enabled entitlement +
explicit action permission + resource scope + applicable consent/BAA rules`.

Build an action-level matrix from each feature's existing business rules. Do not
assume Provider or Consultant should see all clinic records because a role name
sounds appropriate. An undefined action/role pair is denied. If access needs to
be limited to assigned patients/providers, define and enforce that relationship;
a tenant boundary alone cannot supply within-clinic restrictions.

Suggested abuse controls: 72-hour invitation expiry, 60-second resend cooldown,
5 resends per invitation/hour, plus inviter, recipient, workspace and IP budgets
(e.g. 20 creates/inviter/hour and 100/workspace/day). Make limits configurable,
return Retry-After, and tune with real usage; use shared counters, not memory.
Revoking remains possible when a send budget is exhausted.

## 4. Invitation lifecycle and authentication

1. Manager opens the existing User management drawer, enters email and chooses
   from roles the backend says that manager may grant.
2. Server verifies session, CSRF, Origin, current workspace membership and grant
   permission. Validate the email; normalize consistently without treating Gmail
   dots, plus aliases or similar-looking addresses as interchangeable identities.
   Normalize domain case/IDNA; preserve unknown providers' local-part semantics.
   Define and test any provider-specific case normalization explicitly.
3. In one transaction, create the pending invitation, token hash, audit entry,
   encrypted email delivery record, and outbox reference. A repeated UI submit
   with the same scoped idempotency key must not create duplicate sends.
4. Worker sends an email containing a link to the configured app origin. The
   callback URL is never built from Host headers or caller-supplied return URLs.
5. Use `/invite#token=...` for the entry link. The public page extracts and removes
   the fragment immediately, then exchanges it by same-origin POST for a short
   lived, opaque invitation-context cookie. Do not put raw tokens into server
   paths/query strings, browser localStorage, analytics, errors or OAuth state.
6. Context exchange verifies the token/expiry/generation and sets a Secure,
   HttpOnly, SameSite cookie referencing server-side context. Require same-origin
   requests and rate limits, even before login. This exchange grants no access,
   exposes no private workspace details and does not consume the invitation.
7. If logged out, start Google login. Bind the invitation context to the existing
   OAuth transaction/binding cookie; preserve state/nonce/PKCE. Allow only fixed
   internal return destinations. A normal login without a valid invitation flow
   must not implicitly accept invitations by matching an email.
8. After login, send the user to the acceptance confirmation **before onboarding**,
   including users who currently have no membership. Check the freshly verified
   email against the invited address. A wrong account sees Switch account, never
   a join action or another workspace's data.
9. Require a recent login for acceptance (proposed 10 minutes, based on this
   session's authentication timestamp, not another session's user last_login_at).
   Continue using Google `sub` as identity. Do not merge accounts just because
   email strings match. Google is not authoritative for some non-Gmail addresses
   without a hosted-domain claim; require a fresh session-bound mailbox challenge
   for those cases rather than trusting an old `email_verified` claim alone.
10. The user explicitly presses Accept invitation. A CSRF-protected POST rechecks
    token context, email proof, expiry, current invitation role/generation,
    workspace status, account status, and current inviter grant authority.
11. Lock the invitation and workspace/membership records in a defined order,
    atomically create/link the member, mark accepted, write audit and select that
    workspace for the accepting session. Unique constraints handle concurrent
    accepts. Return the existing workspace; never provision a tenant here.
12. Clear the invitation context and refresh auth/permissions, then open the
    workspace home. Other sessions keep their own selected workspace.

Public GETs and email scanner requests must never accept or revoke an invitation.
The invitation landing page uses no-referrer, no-store, no third-party assets or
analytics, and a restrictive CSP. Redact sensitive request fields in API/proxy/
error tooling. A context cookie is a capability and gets the same care as a token.

Expired/revoked/replaced invitations show a safe recovery message and allow
requesting a new invitation through a manager. Never silently create a workspace.
Users entering through ordinary signup can be shown pending-invitation guidance;
do not globally prevent legitimate signup merely because someone invited their
email address, which would itself permit onboarding denial of service.

## 5. Data model and invariants

Add migrations in the existing single Alembic stream, based on the actual latest
head at implementation time. Include RLS, indexes, role grants and bootstrap
changes; verify a fresh database and an upgraded database each have one head.

### `core.workspace_invitations`

Fields: UUID id, tenant_id, invited_email, normalized_email, role, invited_by
staff id, token_hash, token_generation, status, expires_at, accepted_at,
accepted_by_user_id, revoked_at, revoked_by_staff_id, created_at, updated_at,
last_send_requested_at. Status is pending/accepted/revoked/expired; delivery status
is a separate concern. Apply role/status constraints, FK policy and tenant RLS.

- Generate at least 256 bits of cryptographically secure random token material;
  store a cryptographic hash for verification, not the raw token.
- One pending invitation per workspace + canonical email, enforced by a partial
  unique index. Explicitly expire an old pending row under lock before creating a
  replacement; do not use volatile `now()` predicates in a unique index.
- Never return raw token/hash in manager lists or send it to Redis/event payloads.
- Resend rotates token/generation, invalidates old contexts and cancels obsolete
  queued deliveries. Revoke invalidates the same way.
- Recheck inviter authority at dispatch and acceptance. Removing/demoting an
  inviter cancels pending grants that they are no longer authorized to issue;
  an Owner may issue a fresh invitation under their own authority.
- An existing active member is a conflict, not an implicit role overwrite.
- Imported staff records with null user_id may be linked only through a valid
  explicit invitation and an unambiguous identity/email match. A record bound to
  a different user is a conflict. Never silently reactivate a disabled membership.
- Repeated acceptance by the same identity can return success only if the
  existing membership remains active; it must never restore removed access,
  overwrite a later role change or grant a second membership. Other identities
  and consumed/revoked tokens fail safely.
- Management mutations serialize on the workspace row so concurrent actions
  cannot remove/demote the last active Owner. Self-removal and ownership changes
  require explicit safeguards; the invitation API cannot perform them.

### Active workspace

Add nullable `active_workspace_id` to the opaque auth session, with appropriate
FK/grants. Expose an explicit CSRF-protected workspace switch operation. Resolve
`/auth/me` and API request context from this selection, revalidating membership
on every request. A stale/deleted selection becomes a safe chooser/no-access
state, never an arbitrary first membership with different privileges.

A supplied tenant header is context, not authority: validate it against the
session's authorized selection, with explicit development-auth exceptions only
when configured. Replace inconsistent frontend cookie reordering with this
server-authorized source of truth. Use it for client reads/writes, server-rendered
API calls, downloads, voice tickets, WebSockets and jobs. Revalidate long-lived
connections periodically and before privileged actions; removal/demotion must
not leave a live socket able to act indefinitely.

### Delivery and invitation context

- `ops.email_deliveries`: tenant id, template/version, deduplication key, encrypted
  payload, linked resource + generation, status, attempts, next_attempt_at,
  provider message id, safe error code, lease/claim fields and timestamps.
- `auth.invitation_contexts`: hashed opaque context id, invitation id/generation,
  browser/OAuth binding, expiry and consumed state. Bounded lifetime and cleanup.
  Grant only narrow access to the auth role; use system operations for membership
  mutation instead of widening `clinic_auth` to tenant data.
- Encrypt durable payloads containing the email/link with a separate versioned
  application encryption key, held by the API/worker in Secret Manager. Expire and
  erase sensitive payloads after send/terminal failure/expiry; keep only minimal
  delivery/audit metadata under an explicit retention policy. Never persist raw
  secrets in a general JSON outbox, Redis job, console log or analytics property.

## 6. Reusable email architecture and template API

Keep the implementation in the existing shared engagement package:

```text
packages/engagement/src/clinic_engagement/
  email/
    __init__.py              public EmailService / enqueue_email / send_email
    types.py                 typed EmailContent, EmailAddress, DeliveryResult
    service.py               common validation, enqueue and provider interface
    sendgrid.py              async HTTP transport, provider mapping only
    delivery.py              durable claims/retries/status reconciliation
    crypto.py                versioned short-lived payload encryption
    template/
      __init__.py            export invitation and future template factories
      invitation.py          typed variables -> EmailContent
      invitation.html        escaped HTML email
      invitation.txt         plain-text alternative
      email_verification.py  session-bound mailbox challenge, when needed
      email_verification.html
      email_verification.txt
      base.html              shared email presentation
  providers.py               compatibility adapter; leave SMS independent
packages/core/src/clinic_core/
  tenancy/invitations.py     create/accept/revoke domain invariants
  tenancy/permissions.py     grant authority and member management policies
  auth/                     invitation login context and session workspace
packages/db/src/clinic_db/models/
  core.py                   invitation model and membership constraints
  auth.py                   context and active session workspace
  ops.py                    generic delivery records
apps/api/src/clinic_api/routers/
  invitations.py            HTTP composition; core + email service, no feature deps
apps/worker/src/clinic_worker/
  main.py                   dispatch shared email platform events
apps/web/
  app/(auth)/invite/         acceptance flow, outside workspace-required layouts
  components/settings/      real invitations/status/resend/revoke UI
infra/terraform/             email secret references/IAM and worker deployment
```

Templates are packaged with the Python distribution/container, not referenced
through the caller's current working directory. Use strict typed inputs, HTML
escaping/StrictUndefined, plain text, safe URL construction and subject/header
CRLF rejection. Only trusted repository templates are executable; no user-defined
Jinja or filesystem paths. Do not infer template variables from arbitrary dicts.

Planned application usage (illustrative API, not code already present):

```python
from clinic_engagement.email import enqueue_email
from clinic_engagement.email.template import invitation

# Inside the same DB transaction as creating the invitation:
await enqueue_email(
    db,
    tenant_id=workspace.id,
    to=[recipient_email],
    template=invitation(
        workspace_name=workspace.name,
        inviter_name=actor.name,
        role_label=role_label,
        accept_url=server_generated_accept_url,
        expires_at=expires_at,
    ),
    deduplication_key=f"invitation:{invite.id}:{invite.token_generation}",
)
```

Future code imports another template and passes it to the same service. Transport
knows nothing about invitations, workspaces, voice, patient tables or frontend
components. Authorization belongs to the domain caller, not to template code.

Core invitation functions receive a validated transaction and return the data
needed by the API composition layer. The API calls engagement's enqueue function
before that transaction commits. This avoids a forbidden core → engagement import.
The worker uses the same service's immediate transport method after claiming a
committed delivery. SendGrid-specific dependencies and errors stay in sendgrid.py.

Retain existing SMS configuration. Add a separate EMAIL_PROVIDER; choosing
SendGrid for email must not stop Twilio SMS. Adapt the legacy send_email interface
to the shared service as needed; do not route staff invitations through patient
marketing sequences or accidentally bypass those sequences' consent checks.
No public endpoint may accept arbitrary recipients/template bodies as an email relay.
For multi-recipient notifications, use isolated personalizations by default so
recipients cannot see one another; invitations always target exactly one email.
Only trusted backend/worker code imports the service. Browser code calls an
authorized domain endpoint and never receives SendGrid credentials.

## 7. Delivery reliability, SendGrid and deployment

- Only a committed invitation schedules mail. Invitation + delivery + audit +
  outbox reference are one transaction. Events contain delivery id/generation,
  never email bodies or tokens.
- Reuse platform event dispatch, independent of enabled sellable features. A
  workspace invitation must work if Voice Receptionist is deleted or disabled.
- Claim deliveries with leases/locking and a unique deduplication key. An event
  retry does not intentionally enqueue another message. Reconcile due/abandoned
  records so losing Redis state cannot permanently strand committed mail.
- Before sending, verify invitation is still pending, current, unexpired, tenant
  active and inviter still allowed to grant that role. Avoid holding a DB row
  lock across the HTTP request; cancellation/acceptance is ultimately enforced by
  the invitation state even if an email was already in flight.
- Use a fixed HTTPS SendGrid Mail Send endpoint, an injected async HTTP client,
  explicit timeout, bounded exponential retry with jitter and Retry-After for
  throttling. Treat validation/invalid-key/unverified-sender failures as terminal
  configuration/action failures, not endless retries. Handle timeouts/5xx as
  potentially ambiguous; SendGrid may have accepted before the response was lost.
- Provider submission is **at least once**, not exactly once. A rare duplicate
  mail after an ambiguous network failure cannot grant duplicate access.
- Track queued/sending/provider-accepted/failed. A 202 means accepted for
  processing, not delivered. Only verified provider events can mark delivered,
  bounced or dropped. If webhooks are included, verify signatures against raw
  body, check timestamp/replay, deduplicate events and match known message ids.
  If webhooks are deferred, do not display a Delivered badge.
- Disable open/click tracking for security emails so invitation links are not
  rewritten or copied into tracking metadata. Do not include PHI in invitations,
  template examples, custom_args, error logs or test messages.
- Keep console/test providers side-effect-free: return captured messages in tests
  and redact secret fields in development. Never log a full invitation body.
- Production needs the existing worker deployed on a supported sustained worker
  runtime, or a reliable scheduled delivery-drain job with measured latency.
  The inspected Terraform currently defines web/API services; worker deployment
  and monitoring are an explicit release dependency, not an assumption.
- API key and payload encryption key remain server-side. Terraform should manage
  secret resources/references and least-privilege IAM, with secret versions
  provisioned through the approved secret workflow; no keys in tfvars, Git or
  browser-visible NEXT_PUBLIC variables. Grant only required runtime identities.

Proposed environment/configuration:

| Variable | Purpose |
|---|---|
| EMAIL_PROVIDER | console/test/sendgrid, independent of SMS |
| SENDGRID_API_KEY | backend/worker secret; already present locally |
| EMAIL_FROM_ADDRESS / EMAIL_FROM_NAME | verified sender identity |
| EMAIL_REPLY_TO | optional support reply-to |
| PUBLIC_APP_ORIGIN | allowlisted local/production app origin for links |
| EMAIL_PAYLOAD_ENCRYPTION_KEY | separate secret with versioned rotation |
| INVITATION_TTL_HOURS | proposed 72 |
| SENDGRID_WEBHOOK_VERIFICATION_KEY | only if delivery event webhook enabled |

Use a restricted SendGrid key with mail-send permission and authenticated sending
identity/domain. Configure sender authentication/DNS and production secret
injection before enabling real sends. Keep development/test from accidentally
sending to arbitrary real addresses; explicit send mode or sandbox allowlist.

## 8. HTTP and UI contracts

Proposed endpoints, finalized with generated OpenAPI types:

- GET/POST `/api/v1/workspaces/{workspace_id}/invitations`: scoped paginated list /
  create; return role choices/management capabilities and safe delivery status.
- POST `.../invitations/{id}/resend` and `.../{id}/revoke`: scoped and reauthorized.
- POST `/api/v1/invitations/context`: rate-limited same-origin token exchange;
  no private data and no membership mutation.
- GET `/api/v1/invitations/current`: authenticated matching-account preview.
- POST `/api/v1/invitations/accept`: authenticated, fresh-email proof, CSRF and
  atomic membership grant. Role/workspace come from invitation, never the body.
- POST `/api/v1/auth/workspace`: authenticated/CSRF membership-validated switch.
- Subsequent member role/remove endpoints share one management service/policy.

UI: enable the existing drawer only for grantable roles; expose pending/expired/
revoked/accepted and delivery-failed states, resend cooldown, revoke confirmation,
wrong-account recovery, acceptance confirmation, and a workspace switcher when
there is more than one membership. The server is authoritative even when a user
manipulates an interface or submits a stale form. Use shared packages/ui controls.

## 9. Implementation order and release gates

1. **Permission baseline:** inventory every endpoint, route, download and socket;
   define an explicit role/action matrix, add backend guards and derive UI
   capabilities. Include existing features that invitees can reach. Fix the
   active-workspace source of truth and test two-workspace users.
2. **Database/domain:** add the migration, scoped repositories, invitation state
   machine, idempotency, locking, owner protections, rate limits and audit.
3. **Email foundation:** implement provider-independent content/service, template
   exports, SendGrid transport, encrypted durable delivery, worker registration,
   retry/reconciliation and safe errors. Mock transport in routine tests.
4. **Identity/acceptance:** safe landing context, OAuth continuation, fresh matching
   identity/mailbox proof, atomic join and selected-workspace update. Add a
   controlled verification-email template if that proof is required.
5. **User management UI:** connect send/list/resend/revoke and workspace switching;
   replace the current preview notice with actual delivery outcomes. Finish role
   change/removal through the same server policy if included in this release.
6. **Infra/rollout:** provision verified sender/secrets/worker; deploy migrations
   before API/worker; keep invitations behind a server-side enable flag until the
   permission and acceptance suites pass. Roll back issuance without invalidating
   existing members. A single controlled live test needs an agreed recipient.

No stage may bypass the permission baseline simply to make Invite user clickable.

## 10. Required tests and acceptance criteria

**Domain/database:** duplicate invitations and double-clicks; concurrent accepts;
expiry boundary; token replay; resend-old-link invalidation; revoke/accept races;
role change or disabled inviter before acceptance; suspended tenant; inactive
user/member; existing active member; ambiguous imported staff; ownership safety;
transaction rollback leaves neither partial grant nor orphaned queued mail.

**Identity:** wrong Google account, unverified email, forged claims, stale login,
changed email, non-authoritative third-party email, OAuth state/PKCE/nonce/binding
failures, invitation context lost/expired, existing user in another workspace,
multiple invitations, and no tenant creation/trial grant during acceptance.

**Authorization:** each role × each action; forged workspace/member/invite UUIDs;
role body/header manipulation; cross-workspace reads and writes; cached UI after
removal; direct downloads/recordings; WebSocket continuation after demotion;
RLS using the actual restricted database roles. Assert 403/404 without leaked
private data. A hidden link alone never counts as a passing authorization test.

**Email/worker:** escaped hostile names/URLs, CRLF injection, template packaging,
missing sender/key, no secrets in logs/jobs, timeout, 429, 5xx, permanent failure,
worker crash/retry, invalidated queued generations, delivery reconciliation,
provider-accepted vs delivered, forged/replayed webhooks if enabled, and SMS
continues working when EMAIL_PROVIDER changes.

**Browser:** invite → email captured in test transport → Google matching account →
confirm → exact original workspace; wrong account recovery; existing multi-member
workspace selection; pending/resend/revoke states; role-limited navigation and
API access; mobile drawer, keyboard/focus, and session expiry.

Release only after build/typecheck/lint/boundaries and relevant API, worker,
permission and browser suites pass. Verify deleting Voice Receptionist leaves
invitations, email templates and workspace administration functional. Document
operational alerts for delayed/failed deliveries and suspicious invite activity.

## 11. Confirmed deployment inputs and remaining setup

The user confirmed this production application origin:

```text
PUBLIC_APP_ORIGIN=https://prod-avishkar-web-287171356403.us-east1.run.app
```

The provided `/voice-receptionist` suffix is a feature route, not part of the
origin. Build invitation links from `/invite` at the app root. Keep localhost
configuration unchanged for local development, and configure the Google callback
consistently in the production environment.

The user supplied a SendGrid Single Sender Verification screenshot showing a
verified sender with the following values:

```text
EMAIL_FROM_ADDRESS=abhinav.chaudhary@avishkar.app
EMAIL_FROM_NAME=Avishkar AI
EMAIL_REPLY_TO=abhinav.chaudhary@avishkar.app
```

These values replace the initial Gmail sender in local configuration. This is
user-provided evidence of Single Sender Verification; domain authentication and
actual API-key permissions/delivery have not been independently tested. No live
email has been sent. Domain authentication remains the recommended production
setup. The SendGrid signup email can remain different from the sending identity.
Sender changes stay configuration-only.

Remaining inputs:

- Configure domain authentication for production and confirm that the API key
  has mail-send permissions. Single Sender Verification is now confirmed by the
  supplied screenshot.
- Final business approval of the role/action matrix and any within-clinic record
  restrictions. Proposed invite grant rules above are the starting defaults.
- Production secret/worker provisioning ownership; verification webhook decision.
- An approved test recipient when a live end-to-end delivery test is requested.

Planning, schemas, fake-provider tests and UI work can progress without sending
live emails or revealing the API key. Sender/domain readiness blocks real delivery,
not preparatory implementation.

## 12. References

Repository architecture, auth, tenancy, engagement and worker code were inspected
for this plan. External references guide provider/identity/security details:

- [SendGrid Mail Send](https://www.twilio.com/docs/sendgrid/api-reference/mail-send/mail-send)
- [SendGrid API key permissions](https://www.twilio.com/docs/sendgrid/api-reference/api-key-permissions)
- [Single Sender Verification](https://www.twilio.com/docs/sendgrid/ui/sending-email/sender-verification)
- [Sender domain authentication](https://www.twilio.com/docs/sendgrid/ui/account-and-settings/how-to-set-up-domain-authentication)
- [SendGrid Event Webhook security](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/getting-started-event-webhook-security-features)
- [Google OpenID Connect and stable sub identity](https://developers.google.com/identity/openid-connect/openid-connect)
- [Google guidance on non-authoritative email claims](https://developers.google.com/identity/sign-in/android/backend-auth)
- [OWASP authorization guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP single-use URL token handling](https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html)

## Review decisions (2026-10-24)

Provider and Consultant remain reserved, denied-by-default feature roles. They can
sign in and access workspace/account basics, but have no patient/product feature
permissions until a separately reviewed policy is implemented. The shipped access
matrix is in USER_MANAGEMENT.md; invitations never imply clinical access.

Production requests now publish delivery IDs to Cloud Tasks after committing,
using a bounded task-creation call rather than waiting for SendGrid. A separate
private Cloud Run HTTP service authenticates the queue's OIDC caller and processes
the encrypted delivery. Direct sending remains only as the local no-queue fallback.
The 30-minute Scheduler call to the shared email service republishes failed/stale dispatches; generation names,
DB leases and terminal-state checks protect against duplicates. Terraform provisions
scoped queue identities; Deploy updates the private handler before the API. Existing
secret containers are imported, while Terraform manages their versions through
GitHub production credentials and a generated permanent payload key. Values are
redacted in plan text but present in protected Terraform state and saved plans.
Configure old-key compatibility before adopting the generated key if existing
ciphertext may remain. The latest rollout and permissions are in USER_MANAGEMENT.md.
