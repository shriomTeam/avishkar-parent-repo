"use client";
import { useState } from "react";
import type { Schemas } from "@clinic/api-client";
import {
  Alert,
  Avatar,
  Button,
  DataTable,
  Dialog,
  DialogActions,
  Dropdown,
  EmptyState,
  Input,
  Note,
  Panel,
  PanelHead,
  StatusBadge,
  Td,
  TextField,
  Th,
  Tr,
} from "@clinic/ui";
import { Plus } from "lucide-react";
import { initials } from "@/lib/auth/types";
import { useAuth } from "@/lib/auth/provider";
import { useWorkspaceResource } from "./use-workspace-resource";

const roleOptions = [
  "owner",
  "office_manager",
  "front_desk",
  "provider",
  "consultant",
].map((value) => ({ value, label: value.replaceAll("_", " ") }));
export function Members({
  workspaceId,
  userId,
  canManage,
}: {
  workspaceId: string;
  userId: string;
  canManage: boolean;
}) {
  const { write, auth } = useAuth();
  const role =
    auth.memberships.find((m) => m.workspace_id === workspaceId)?.role ?? "";
  const [query, setQuery] = useState("");
  const [filterRole, setFilterRole] = useState("all");
  const [status, setStatus] = useState("all");
  const [invite, setInvite] = useState(false);
  const [reinvite, setReinvite] = useState<
    Schemas["WorkspaceMemberOut"] | null
  >(null);
  const [edit, setEdit] = useState<Schemas["WorkspaceMemberOut"] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const members = useWorkspaceResource<Schemas["WorkspaceMemberOut"][]>(
    `/api/v1/workspaces/${workspaceId}/members`,
    canManage,
  );
  const invitations = useWorkspaceResource<Schemas["InvitationList"]>(
    `/api/v1/workspaces/${workspaceId}/invitations`,
    canManage,
  );
  const roles = invitations.data?.grantable_roles ?? [];
  const filtered = members.data?.filter(
    (m) =>
      `${m.name} ${m.email}`.toLowerCase().includes(query.toLowerCase()) &&
      (filterRole === "all" || m.role === filterRole) &&
      (status === "all" || (m.active ? "active" : "inactive") === status),
  );
  const act = async (
    path: string,
    body?: unknown,
    success = "Change saved.",
  ) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await write(path, body);
      setMessage(success);
      members.retry();
      invitations.retry();
      return true;
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not save this change.",
      );
      return false;
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="grid gap-6">
      {error && <Alert>{error}</Alert>}
      {message && (
        <p role="status" className="text-sm text-brand-ink">
          {message}
        </p>
      )}
      <Panel>
        <PanelHead
          title="Workspace members"
          action={
            canManage && (
              <Button
                variant="brand"
                disabled={!invitations.data?.enabled}
                onClick={() => {
                  setReinvite(null);
                  setError("");
                  setInvite(true);
                }}
              >
                <Plus size={16} aria-hidden="true" />
                Invite user
              </Button>
            )
          }
        />
        <p className="-mt-2 mb-6 text-[13px] text-muted">
          Manage who can access your clinic workspace.
        </p>
        {!canManage ? (
          <Note>
            Only workspace owners and office managers can manage members.
          </Note>
        ) : (
          <>
            {invitations.data && !invitations.data.enabled && (
              <Note>
                Email invitations are not configured for this environment yet.
              </Note>
            )}
            <div className="my-5 grid gap-3 lg:grid-cols-[minmax(180px,1fr)_180px_160px]">
              <Input
                aria-label="Search members"
                placeholder="Search by name or email"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <Dropdown
                label="Filter by role"
                hideLabel
                flush
                value={filterRole}
                onChange={setFilterRole}
                options={[{ value: "all", label: "All roles" }, ...roleOptions]}
              />
              <Dropdown
                label="Filter by status"
                hideLabel
                flush
                value={status}
                onChange={setStatus}
                options={[
                  { value: "all", label: "All statuses" },
                  { value: "active", label: "Active" },
                  { value: "inactive", label: "Inactive" },
                ]}
              />
            </div>
            {members.error ? (
              <Alert>
                {members.error}
                <Button variant="outline" onClick={members.retry}>
                  Retry
                </Button>
              </Alert>
            ) : !members.data ? (
              <p role="status">Loading workspace members…</p>
            ) : !filtered?.length ? (
              <EmptyState
                title="No members found"
                description="Try a different name, email or filter."
              />
            ) : (
              <DataTable>
                <thead>
                  <tr>
                    <Th>Member</Th>
                    <Th>Role</Th>
                    <Th>Status</Th>
                    <Th>Added</Th>
                    <Th>Actions</Th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((m) => (
                    <Tr key={m.id}>
                      <Td>
                        <div className="flex items-center gap-3">
                          <Avatar>{initials(m.name)}</Avatar>
                          <div>
                            <p className="font-medium">
                              {m.name}{" "}
                              {m.user_id === userId && (
                                <span className="ml-1 rounded bg-brand-soft px-1.5 py-0.5 text-[10px] text-brand-ink">
                                  You
                                </span>
                              )}
                            </p>
                            <p className="mt-1 text-xs text-muted">{m.email}</p>
                          </div>
                        </div>
                      </Td>
                      <Td>
                        <span className="capitalize">
                          {m.role.replaceAll("_", " ")}
                        </span>
                      </Td>
                      <Td>
                        <StatusBadge tone={m.active ? "brand" : "muted"}>
                          {m.active ? "Active" : "Inactive"}
                        </StatusBadge>
                      </Td>
                      <Td>
                        {new Date(m.created_at).toLocaleDateString("en-GB", {
                          timeZone: "UTC",
                        })}
                      </Td>
                      <Td>
                        {!m.active && m.user_id && roles.includes(m.role) && (
                          <Button
                            variant="outline"
                            disabled={busy || !invitations.data?.enabled}
                            onClick={() => {
                              setReinvite(m);
                              setError("");
                              setInvite(true);
                            }}
                          >
                            Re-invite {m.name}
                          </Button>
                        )}
                        {m.active &&
                          m.user_id !== userId &&
                          roles.includes(m.role) && (
                            <Button
                              variant="outline"
                              onClick={() => setEdit(m)}
                            >
                              Manage {m.name}
                            </Button>
                          )}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </DataTable>
            )}
            <p className="mt-5 text-xs leading-5 text-muted">
              Owners control manager access. Office managers can manage front
              desk, provider and consultant memberships. Owner access cannot be
              changed here.
            </p>
          </>
        )}
      </Panel>
      {canManage && (
        <Panel>
          <PanelHead
            title="Invitations"
            action={
              <Button
                variant="outline"
                onClick={() => {
                  invitations.retry();
                  members.retry();
                }}
              >
                Refresh invitations
              </Button>
            }
          />
          {invitations.error ? (
            <Alert>
              {invitations.error}
              <Button variant="outline" onClick={invitations.retry}>
                Retry
              </Button>
            </Alert>
          ) : !invitations.data ? (
            <p role="status">Loading invitations…</p>
          ) : !invitations.data.invitations.length ? (
            <EmptyState
              title="No pending invitations"
              description="Accepted members appear in Workspace members. Invite someone new to join your workspace."
            />
          ) : (
            <DataTable>
              <thead>
                <tr>
                  <Th>Email</Th>
                  <Th>Role</Th>
                  <Th>Status</Th>
                  <Th>Email delivery</Th>
                  <Th>Actions</Th>
                </tr>
              </thead>
              <tbody>
                {invitations.data.invitations.map((item) => (
                  <Tr key={item.id}>
                    <Td>{item.email}</Td>
                    <Td>
                      <span className="capitalize">
                        {item.role.replaceAll("_", " ")}
                      </span>
                    </Td>
                    <Td>
                      <StatusBadge
                        tone={item.status === "pending" ? "warn" : "muted"}
                      >
                        {item.status}
                      </StatusBadge>
                    </Td>
                    <Td>
                      {item.delivery_status === "accepted"
                        ? "Accepted by email provider"
                        : item.delivery_status}
                    </Td>
                    <Td>
                      {["pending", "expired"].includes(item.status) &&
                        roles.includes(item.role) && (
                          <div className="flex gap-2">
                            <Button
                              variant="outline"
                              disabled={busy}
                              onClick={() =>
                                void act(
                                  `/api/v1/workspaces/${workspaceId}/invitations/${item.id}/resend`,
                                  undefined,
                                  "New invitation link created. Previous links no longer work.",
                                )
                              }
                            >
                              Resend
                            </Button>
                            <Button
                              variant="dangerOutline"
                              disabled={busy}
                              onClick={() => {
                                if (
                                  window.confirm(
                                    `Revoke the invitation for ${item.email}?`,
                                  )
                                )
                                  void act(
                                    `/api/v1/workspaces/${workspaceId}/invitations/${item.id}/revoke`,
                                    undefined,
                                    "Invitation revoked.",
                                  );
                              }}
                            >
                              Revoke
                            </Button>
                          </div>
                        )}
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </DataTable>
          )}
        </Panel>
      )}
      {invite && (
        <InviteUser
          roles={roles}
          member={reinvite}
          error={error}
          onClose={() => setInvite(false)}
          onSend={async (body) => {
            const ok = await act(
              `/api/v1/workspaces/${workspaceId}/invitations`,
              body,
              "Invitation created. Its email delivery status appears below.",
            );
            if (ok) setInvite(false);
            return ok;
          }}
        />
      )}
      {edit && (
        <MemberDialog
          member={edit}
          roles={roles}
          onClose={() => setEdit(null)}
          onSave={async (body) => {
            const ok = await act(
              `/api/v1/workspaces/${workspaceId}/members/${edit.id}`,
              body,
            );
            if (ok) setEdit(null);
            return ok;
          }}
        />
      )}
      <span className="sr-only">Current role: {role}</span>
    </div>
  );
}
function InviteUser({
  roles,
  member,
  error,
  onClose,
  onSend,
}: {
  roles: string[];
  onClose: () => void;
  onSend: (body: { email: string; role: string }) => Promise<boolean>;
  error: string;
  member: Schemas["WorkspaceMemberOut"] | null;
}) {
  const [role, setRole] = useState(
    member?.role ??
      (roles.includes("front_desk") ? "front_desk" : (roles[0] ?? "")),
  );
  const [email, setEmail] = useState(member?.email ?? "");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  return (
    <Dialog
      title={member ? "Re-invite member" : "Invite user"}
      onClose={onClose}
      placement="right"
    >
      <form
        className="flex min-h-[calc(100dvh-130px)] flex-col"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setFailed(false);
          const ok = await onSend({ email: email.trim(), role });
          if (!ok) {
            setBusy(false);
            setFailed(true);
          }
        }}
      >
        <p className="mb-6 text-sm text-muted">
          {member
            ? "Send a fresh invitation to restore this member’s access. They stay inactive until they sign in with their original account and accept. Choose the role they should have when they return."
            : "Give someone access to this workspace. They must sign in with the invited email and accept before they can access it."}
        </p>
        <TextField
          label="Email address"
          type="email"
          required
          maxLength={254}
          value={email}
          readOnly={Boolean(member)}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="name@clinic.com"
          autoComplete="email"
        />
        <Dropdown
          label="Role"
          options={roleOptions.filter((r) => roles.includes(r.value))}
          value={role}
          onChange={setRole}
          disabled={busy}
        />
        <Note>
          The invitation email includes its expiry time. Access is limited by
          the assigned role and this workspace’s enabled products.
        </Note>
        {failed && (
          <Alert>
            {error || "Could not create this invitation. Please retry."}
          </Alert>
        )}
        <div className="mt-auto pt-8">
          <DialogActions>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={onClose}
            >
              Cancel
            </Button>
            <Button type="submit" variant="brand" disabled={busy || !role}>
              {busy ? "Sending…" : "Send invitation"}
            </Button>
          </DialogActions>
        </div>
      </form>
    </Dialog>
  );
}
function MemberDialog({
  member,
  roles,
  onClose,
  onSave,
}: {
  member: Schemas["WorkspaceMemberOut"];
  roles: string[];
  onClose: () => void;
  onSave: (body: { role?: string; deactivate?: boolean }) => Promise<boolean>;
}) {
  const [role, setRole] = useState(member.role);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const save = async (body: { role?: string; deactivate?: boolean }) => {
    setBusy(true);
    setFailed(false);
    if (!(await onSave(body))) {
      setBusy(false);
      setFailed(true);
    }
  };
  return (
    <Dialog title={`Manage ${member.name}`} onClose={onClose}>
      <p className="mb-5 text-sm text-muted">{member.email}</p>
      <Dropdown
        label="Member role"
        value={role}
        onChange={setRole}
        options={roleOptions.filter((r) => roles.includes(r.value))}
        disabled={busy}
      />
      <p className="mb-5 text-xs text-muted">
        Removing access does not delete this person’s account or affect their
        other workspaces.
      </p>
      {failed && (
        <Alert>
          Could not update this member. Refresh and check your permissions.
        </Alert>
      )}
      <DialogActions>
        <Button
          variant="dangerOutline"
          disabled={busy}
          onClick={() => {
            if (window.confirm(`Remove ${member.name} from this workspace?`))
              void save({ deactivate: true });
          }}
        >
          Remove access
        </Button>
        <Button
          variant="brand"
          disabled={busy || role === member.role}
          onClick={() => void save({ role })}
        >
          Save role
        </Button>
      </DialogActions>
    </Dialog>
  );
}
