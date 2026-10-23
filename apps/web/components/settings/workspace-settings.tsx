"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { Schemas } from "@clinic/api-client";
import {
  Alert,
  Avatar,
  Button,
  Dropdown,
  Note,
  PageHeading,
  Panel,
  PanelHead,
  SidebarLayout,
  StatusBadge,
  Tabs,
  TextField,
} from "@clinic/ui";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "@/lib/auth/provider";
import { initials } from "@/lib/auth/types";
import { Members } from "./members";
import { AuditLog } from "./audit-log";

type Workspace = Schemas["WorkspaceSettingsOut"];
const commonTimezones = [
  "UTC",
  "Asia/Kolkata",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Australia/Sydney",
];
export const roleLabel = (role: string) => role.replaceAll("_", " ");
export function WorkspaceSettings({
  workspace,
  role,
  user,
  activeProducts,
}: {
  workspace: Workspace;
  role: string;
  user: Schemas["UserOut"];
  activeProducts: number;
}) {
  const [tab, setTab] = useState("Workspace");
  const canManage = role === "owner" || role === "office_manager";
  return (
    <div className="mx-auto max-w-[1400px]">
      <PageHeading
        title="Settings"
        description="Manage your workspace, people and preferences in one place."
      />
      <Tabs
        tabs={[
          "Workspace",
          "User management",
          "Privacy & retention",
          "Audit log",
        ]}
        value={tab}
        onChange={setTab}
        label="Settings sections"
      />
      <div role="tabpanel" aria-label={tab}>
        {tab === "Workspace" && (
          <SidebarLayout className="max-xl:grid-cols-1">
            <WorkspaceForm workspace={workspace} canManage={canManage} />
            <div className="grid content-start gap-5">
              <Panel>
                <PanelHead
                  title={
                    <span className="flex items-center gap-2">
                      <ShieldCheck
                        size={19}
                        className="text-brand-ink"
                        aria-hidden="true"
                      />
                      Workspace access
                    </span>
                  }
                />
                <dl className="text-[13px]">
                  <div className="flex justify-between gap-3 border-b border-line py-3">
                    <dt className="text-muted">Your role</dt>
                    <dd className="font-medium capitalize">
                      {roleLabel(role)}
                    </dd>
                  </div>
                  <div className="flex items-center justify-between gap-3 border-b border-line py-3">
                    <dt className="text-muted">Plan status</dt>
                    <dd>
                      <StatusBadge>{workspace.status}</StatusBadge>
                    </dd>
                  </div>
                </dl>
                <p className="py-4 text-[13px]">
                  {activeProducts} active{" "}
                  {activeProducts === 1 ? "product" : "products"}
                </p>
                <p className="border-t border-line pt-4 text-[12px] leading-5 text-muted">
                  Only workspace owners and office managers can update these
                  details.
                </p>
              </Panel>
              <Panel>
                <PanelHead title="Your account" />
                <div className="flex items-center gap-3">
                  <Avatar tone="dark">{initials(user.display_name)}</Avatar>
                  <div className="min-w-0">
                    <p className="text-[13px] font-semibold">
                      {user.display_name}
                    </p>
                    <p className="mt-1 break-all text-[12px] text-muted">
                      {user.email}
                    </p>
                  </div>
                </div>
                <p className="mt-4 text-[12px] text-muted">
                  Signed in with Google
                </p>
              </Panel>
            </div>
          </SidebarLayout>
        )}
        {tab === "User management" && (
          <Members
            workspaceId={workspace.id}
            userId={user.id}
            canManage={canManage}
          />
        )}
        {tab === "Privacy & retention" && (
          <Panel>
            <PanelHead title="Privacy & retention" />
            <p className="mb-5 text-sm text-muted">
              Shared privacy information for this clinic workspace.
            </p>
            <dl className="mb-5 text-sm">
              <dt className="text-muted">Business associate agreement</dt>
              <dd className="mt-2">
                <StatusBadge tone={workspace.baa_signed_at ? "brand" : "warn"}>
                  {workspace.baa_signed_at ? "Signed" : "Not signed"}
                </StatusBadge>
              </dd>
            </dl>
            <Note>
              Sensitive workflows require a signed BAA and patient consent.
              Workspace-wide recording and retention controls are not available
              yet. Your existing recording and retention policies remain in
              effect.
            </Note>
          </Panel>
        )}
        {tab === "Audit log" && (
          <AuditLog
            workspaceId={workspace.id}
            canManage={canManage}
            timezone={workspace.timezone}
          />
        )}
      </div>
    </div>
  );
}

function WorkspaceForm({
  workspace,
  canManage,
}: {
  workspace: Workspace;
  canManage: boolean;
}) {
  const { write, refresh } = useAuth();
  const router = useRouter();
  const initial = {
    name: workspace.name,
    clinic_type: workspace.clinic_type,
    timezone: workspace.timezone,
    phone: workspace.phone ?? "",
    address: workspace.address,
  };
  const [form, setForm] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);
  const change = (field: keyof typeof form, value: string) => {
    setForm((previous) => ({ ...previous, [field]: value }));
    setSaved(false);
    setError("");
  };
  return (
    <Panel>
      <PanelHead title="Workspace information" />
      <p className="-mt-2 mb-6 text-[13px] text-muted">
        Keep your clinic details up to date across every product.
      </p>
      <div className="mb-6 flex items-center gap-3">
        <Avatar size="lg">{initials(form.name)}</Avatar>
        <div>
          <p className="text-sm font-medium">{workspace.name}</p>
          <p className="mt-1 text-xs text-muted">Workspace identity</p>
        </div>
      </div>
      {!canManage && (
        <Note>
          Contact your workspace owner or office manager to edit these details.
        </Note>
      )}
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          setBusy(true);
          setError("");
          setSaved(false);
          try {
            const response = await write(
              `/api/v1/workspaces/${workspace.id}/settings`,
              {
                ...form,
                phone: form.phone.trim() || null,
              },
            );
            const updated: Workspace = await response.json();
            setForm({
              name: updated.name,
              clinic_type: updated.clinic_type,
              timezone: updated.timezone,
              phone: updated.phone ?? "",
              address: updated.address,
            });
            setSaved(true);
            await refresh();
            router.refresh();
          } catch (cause) {
            setError(
              cause instanceof Error
                ? cause.message
                : "Could not save workspace information.",
            );
          } finally {
            setBusy(false);
          }
        }}
      >
        <fieldset
          disabled={!canManage || busy}
          className="min-w-0 disabled:opacity-70"
        >
          <div className="grid gap-x-5 gap-y-1 sm:grid-cols-2">
            <TextField
              label="Workspace name"
              required
              maxLength={80}
              value={form.name}
              onChange={(event) => change("name", event.target.value)}
            />
            <Dropdown
              label="Clinic type"
              value={form.clinic_type}
              onChange={(value) => change("clinic_type", value)}
              options={[
                { value: "wellness", label: "Wellness" },
                { value: "medspa", label: "Medspa" },
                { value: "hrt", label: "HRT" },
              ]}
              disabled={!canManage || busy}
            />
            <Dropdown
              label="Timezone"
              value={form.timezone}
              onChange={(value) => change("timezone", value)}
              options={Array.from(
                new Set([workspace.timezone, ...commonTimezones]),
              ).map((value) => ({ value, label: value }))}
              disabled={!canManage || busy}
            />
            <TextField
              label="Callback number"
              type="tel"
              value={form.phone}
              pattern="\+[1-9][0-9]{6,14}"
              hint="Include the country code, for example +919876543210."
              onChange={(event) => change("phone", event.target.value)}
            />
          </div>
          <TextField
            label="Clinic address"
            value={form.address}
            maxLength={500}
            onChange={(event) => change("address", event.target.value)}
          />
          <p className="text-[12px] text-muted">
            Times and scheduling use this workspace timezone.
          </p>
        </fieldset>
        {error && <Alert>{error}</Alert>}
        {saved && (
          <p role="status" className="mt-4 text-sm text-brand-ink">
            Workspace information saved.
          </p>
        )}
        <div className="mt-6 flex justify-end gap-3 border-t border-line pt-5">
          <Button
            type="button"
            variant="outline"
            disabled={!dirty || busy}
            onClick={() => {
              setForm(initial);
              setSaved(false);
              setError("");
            }}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant="brand"
            disabled={!canManage || busy || !dirty}
          >
            {busy ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}
