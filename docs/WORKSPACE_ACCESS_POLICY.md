# Workspace access policy: trial expiry paused

Effective code change: 26 October 2026. Billing/payments are not implemented, so
automatic 14-day onboarding trial expiry is disabled during product development.
The workspace and its data were never deleted on expiry; expiring feature grants
made products disappear from navigation and returned feature-access errors.

## Current policy

New workspaces are created with `status=active` and `trial_ends_at=NULL`.
The existing starter-product allowlist is unchanged: packages marked
`trial_eligible` receive enabled entitlements with `expires_at=NULL`. Today those
are Patient Blueprints, Dormant Patients (reactivation) and Voice Receptionist.
The development demo seed also creates an active workspace without its former
30-day deadline. The dev-only admin endpoint still supports an explicitly requested
`trial_days` value; it does not grant trials by default and is not mounted in production.

The `trial_eligible` metadata is temporarily reused as an allowlist, not an expiry
policy; the other products are not automatically granted.

Membership, role permissions, explicit product disablement, workspace suspension,
BAA checks and tenant isolation still apply. Sessions, invitation links and email
verification codes still expire. This policy does not bypass general entitlement
expiry checks or change their behavior for explicitly time-limited grants.

## Existing workspaces

Run `pnpm db:migrate` before deploying/restarting the API. Migration
`20261026_pause_trials`, after `20261024_email_tasks`, clears only enabled
entitlement expiries matching their trial workspace's exact `trial_ends_at`.
Those trial workspaces become active with no trial deadline. Expired automatic
trials regain the previously enabled starter products. No missing feature grants
are created and no disabled products are enabled. Suspended workspaces and
independently assigned expiry dates are untouched.

This is a data-only migration. Its downgrade deliberately does not invent old
expiry dates or revoke access. The original deadline values cannot be recovered
from these updated rows; retain normal backups if historical dates are required.
Production changes only when this migration and updated application are deployed;
local changes do not update GCP.

## Bringing trials back with billing

The original 14-day calculation, trial status/deadline assignment and expiring
feature grant are commented in `packages/core/src/clinic_core/tenancy/service.py`.
The existing trial fields, feature metadata and generic entitlement checks remain.
Do not just uncomment the lines and start expiring current users. First implement
subscription/payment handling, a deliberate policy for existing active workspaces,
clear expiry/grace/upgrade UI and permission-reviewed administrative controls.
Then restore provisioning and add an explicit rollout/data migration plus tests.


## Product readiness

Availability is separate from entitlement and role access. Blueprints,
reactivation and Voice Receptionist are implemented. Command Center, Lead
Response, Photos, Reviews and Scribe currently declare `available=False` in their
feature metadata because their endpoints are stubs. The homepage labels these
**Upcoming**, provides no Open link and omits their navigation, even if a stale
entitlement exists. Implemented products show Active when enabled and Inactive
when explicitly disabled; role and entitlement restrictions remain enforced.
When a product is completed, its team can change the availability metadata and
provision its workspace entitlements through the normal platform flow.
