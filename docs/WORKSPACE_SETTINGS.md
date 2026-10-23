# Shared workspace settings

Open the bottom-left profile menu and select **Settings**. The menu also contains
**Sign out**. The platform and Voice Receptionist use the shared `AccountMenu` UI;
the old `/voice-receptionist/settings` URL redirects to `/settings`.

## Available now

- Workspace name, clinic type, IANA timezone, callback number and clinic address
  persist to the existing tenant record. Owners and office managers can save;
  other active members can view their workspace details.
- Managers can view actual workspace members, search by name/email and filter by
  existing role or active status. This is the canonical staff list, not sample data.
- Managers can view the latest 100 tenant-scoped audit events. Workspace changes
  append an audit event in the same transaction as the update.
- Privacy shows the actual BAA status. Editing workspace details cannot grant a
  BAA, change a plan or modify unrelated tenant configuration.

## User management

Invitations, acceptance, resend/revoke, role changes and member removal are now
implemented. See [User management](USER_MANAGEMENT.md) for setup, role rules,
email delivery and deployment requirements.

## Other follow-up

- Workspace-wide recording/retention enforcement and logo uploads are not added
  by this change. The old voice-specific simulated settings have been removed.

## API and boundaries

Shared endpoints are `/api/v1/workspaces/{workspace_id}/settings` (GET/POST),
`/members` (GET), and `/audit` (GET). They require a verified session; writes also
require CSRF and a matching Origin. Membership and role are checked against the
current database, including inactive/suspended workspace denial. A client role
header cannot authorize these operations.

Schemas and management operations live in `packages/core`; HTTP routes live in
`apps/api`. The frontend uses generated API types. No platform settings code
imports Voice Receptionist. Removing the feature does not remove Settings.
