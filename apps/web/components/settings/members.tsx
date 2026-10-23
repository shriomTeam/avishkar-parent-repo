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
import { Plus, Search } from "lucide-react";
import { initials } from "@/lib/auth/types";
import { useWorkspaceResource } from "./use-workspace-resource";

const roles = [
  { value: "owner", label: "Owner" },
  { value: "office_manager", label: "Office manager" },
  { value: "front_desk", label: "Front desk" },
  { value: "provider", label: "Provider" },
  { value: "consultant", label: "Consultant" },
];
export function Members({
  workspaceId,
  userId,
  canManage,
}: {
  workspaceId: string;
  userId: string;
  canManage: boolean;
}) {
  const [query, setQuery] = useState("");
  const [role, setRole] = useState("all");
  const [status, setStatus] = useState("all");
  const [invite, setInvite] = useState(false);
  const { data, error, retry } = useWorkspaceResource<
    Schemas["WorkspaceMemberOut"][]
  >(`/api/v1/workspaces/${workspaceId}/members`, canManage);
  const filtered = data?.filter(
    (member) =>
      `${member.name} ${member.email}`
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (role === "all" || member.role === role) &&
      (status === "all" || (member.active ? "active" : "inactive") === status),
  );
  return (
    <>
      <Panel>
        <PanelHead
          title="Workspace members"
          action={
            canManage && (
              <Button variant="brand" onClick={() => setInvite(true)}>
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
            Only workspace owners and office managers can view the workspace
            member list.
          </Note>
        ) : (
          <>
            <div className="mb-5 grid gap-3 lg:grid-cols-[minmax(180px,1fr)_180px_160px]">
              <label className="relative">
                <span className="sr-only">Search members</span>
                <Search
                  size={17}
                  className="pointer-events-none absolute top-3.5 left-3 text-muted"
                  aria-hidden="true"
                />
                <Input
                  className="pl-10"
                  placeholder="Search by name or email"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <Dropdown
                label="Filter by role"
                hideLabel
                flush
                value={role}
                onChange={setRole}
                options={[{ value: "all", label: "All roles" }, ...roles]}
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
            {error ? (
              <Alert>
                {error}{" "}
                <Button variant="outline" onClick={retry}>
                  Retry
                </Button>
              </Alert>
            ) : !data ? (
              <p role="status" className="py-8 text-sm text-muted">
                Loading workspace members…
              </p>
            ) : filtered?.length ? (
              <DataTable>
                <thead>
                  <tr>
                    <Th>Member</Th>
                    <Th>Role</Th>
                    <Th>Status</Th>
                    <Th>Added</Th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((member) => (
                    <Tr key={member.id}>
                      <Td>
                        <div className="flex items-center gap-3">
                          <Avatar>{initials(member.name)}</Avatar>
                          <div>
                            <p className="font-medium">
                              {member.name}{" "}
                              {member.user_id === userId && (
                                <span className="ml-1 rounded bg-brand-soft px-1.5 py-0.5 text-[10px] text-brand-ink">
                                  You
                                </span>
                              )}
                            </p>
                            <p className="mt-1 text-xs text-muted">
                              {member.email}
                            </p>
                          </div>
                        </div>
                      </Td>
                      <Td>
                        <span className="capitalize">
                          {member.role.replaceAll("_", " ")}
                        </span>
                      </Td>
                      <Td>
                        <StatusBadge tone={member.active ? "brand" : "muted"}>
                          {member.active ? "Active" : "Inactive"}
                        </StatusBadge>
                      </Td>
                      <Td>
                        {new Date(member.created_at).toLocaleDateString(
                          "en-GB",
                          { timeZone: "UTC" },
                        )}
                      </Td>
                    </Tr>
                  ))}
                </tbody>
              </DataTable>
            ) : (
              <EmptyState
                title="No members found"
                description="Try a different name, email or filter."
              />
            )}
            <p className="mt-5 text-[12px] leading-5 text-muted">
              Access follows the workspace’s existing roles. Role changes and
              removing members will be added with user management.
            </p>
          </>
        )}
      </Panel>
      {invite && <InviteUser onClose={() => setInvite(false)} />}
    </>
  );
}

function InviteUser({ onClose }: { onClose: () => void }) {
  const [role, setRole] = useState("front_desk");
  return (
    <Dialog title="Invite user" onClose={onClose} placement="right">
      <div className="flex min-h-[calc(100dvh-130px)] flex-col">
        <p className="mb-6 text-sm text-muted">
          Give someone access to this workspace.
        </p>
        <TextField
          label="Email address"
          type="email"
          placeholder="name@clinic.com"
          autoComplete="email"
        />
        <Dropdown
          label="Role"
          options={roles.filter((item) => item.value !== "owner")}
          value={role}
          onChange={setRole}
        />
        <p className="mb-6 text-xs leading-5 text-muted">
          Access will be limited by their assigned role.
        </p>
        <Note>
          Invitations are coming soon. Sending invitations and granting new
          access are not available yet.
        </Note>
        <div className="mt-auto pt-8">
          <DialogActions>
            <Button variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="brand" disabled>
              Send invitation
            </Button>
          </DialogActions>
        </div>
      </div>
    </Dialog>
  );
}
