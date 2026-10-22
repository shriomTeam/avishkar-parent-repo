"use client";
import { useState } from "react";
import { useDemo } from "../lib/demo/provider";
import { useAuth } from "@clinic/core/web/auth/provider";
import { initials } from "@clinic/core/web/auth/types";
import { SignOut } from "@clinic/core/web/auth/sign-out";
import { dateLabel } from "../lib/format";
import {
  Avatar,
  Button,
  buttonStyles,
  DataTable,
  H2,
  Muted,
  Note,
  Panel,
  PanelHead,
  SummaryList,
  Td,
  Th,
  Tr,
  TwoColumns,
} from "@clinic/ui";
import { Heading, Tabs, Dropdown, Switch, Badge, ResetDemo } from "./ui";
import type { Workspace } from "../lib/types";
function PrivacyForm({ workspace }: { workspace: Workspace }) {
  const { run, busy } = useDemo();
  const [privacy, setPrivacy] = useState(workspace);
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void run(
          {
            type: "save-workspace",
            workspace: {
              ...workspace,
              recordCalls: privacy.recordCalls,
              transcriptRetention: privacy.transcriptRetention,
              recordingRetention: privacy.recordingRetention,
            },
          },
          "Privacy preferences saved in demo",
        );
      }}
    >
      <H2>Call data settings</H2>
      <Switch
        label="Store call recordings"
        description="Only enable after reviewing consent and provider agreements."
        checked={privacy.recordCalls}
        onChange={(recordCalls) => setPrivacy({ ...privacy, recordCalls })}
      />
      <TwoColumns className="mt-5">
        <Dropdown
          label="Transcript retention"
          value={privacy.transcriptRetention}
          onChange={(transcriptRetention) =>
            setPrivacy({ ...privacy, transcriptRetention })
          }
          options={["30 days", "90 days", "180 days"].map((x) => ({
            value: x,
            label: x,
          }))}
        />
        <Dropdown
          label="Recording retention"
          value={privacy.recordingRetention}
          onChange={(recordingRetention) =>
            setPrivacy({ ...privacy, recordingRetention })
          }
          options={["7 days", "30 days", "90 days"].map((x) => ({
            value: x,
            label: x,
          }))}
        />
      </TwoColumns>
      <Note>
        These demo preferences do not configure real recording or retention.
        Existing sample call fixtures remain unchanged.
      </Note>
      <Button type="submit" variant="brand" className="mt-5" disabled={busy}>
        Save preferences
      </Button>
    </form>
  );
}
export function Settings() {
  const { state } = useDemo();
  const { auth } = useAuth();
  const [tab, setTab] = useState("Workspace");
  if (!state) return null;
  return (
    <>
      <Heading
        demo
        title="Settings"
        description="Your workspace, team and call data preferences."
        actions={
          <>
            <ResetDemo />
          </>
        }
      />
      <Panel className="mb-6 max-w-[1000px]" aria-label="Your account">
        <div className="flex items-center justify-between gap-3 max-app:flex-wrap">
          <div className="flex items-center gap-2.5 max-app:flex-wrap">
            <Avatar tone="dark">{initials(auth.user.display_name)}</Avatar>
            <div>
              <H2>{auth.user.display_name}</H2>
              <small className="block text-[12px] text-muted">
                {auth.user.email} · {auth.memberships[0]?.role || "Member"}
              </small>
            </div>
          </div>
          <SignOut
            className={buttonStyles("outline")}
            errorClassName="my-3 rounded-lg bg-danger-soft px-3.5 py-2.5 text-danger-ink"
          />
        </div>
      </Panel>
      <Tabs
        tabs={["Workspace", "Team", "Privacy & retention", "Audit log"]}
        value={tab}
        onChange={setTab}
      />
      <Panel className="max-w-[1000px]" role="tabpanel" aria-label={tab}>
        {tab === "Workspace" && (
          <>
            <H2>Workspace details</H2>
            <Muted className="mb-[25px]">
              Practice information used across your agents.
            </Muted>
            <SummaryList
              items={[
                ["Name", auth.workspace?.name],
                ["Timezone", auth.workspace?.timezone],
                ["Callback number", auth.workspace?.phone || "Not set"],
              ]}
            />
            <Muted className="mt-5">
              Workspace details are saved in your account. Editing will be added
              with the workspace management API.
            </Muted>
          </>
        )}
        {tab === "Team" && (
          <>
            <H2>Workspace team</H2>
            <Muted>Your actual workspace membership.</Muted>
            <DataTable>
              <thead>
                <tr>
                  <Th>Member</Th>
                  <Th>Role</Th>
                  <Th>Status</Th>
                </tr>
              </thead>
              <tbody>
                <Tr>
                  <Td>
                    {auth.user.display_name}
                    <small className="block text-[12px] text-muted">
                      {auth.user.email}
                    </small>
                  </Td>
                  <Td>{auth.memberships[0]?.role || "Member"}</Td>
                  <Td>
                    <Badge>Active</Badge>
                  </Td>
                </Tr>
              </tbody>
            </DataTable>
          </>
        )}
        {tab === "Privacy & retention" && (
          <PrivacyForm
            key={JSON.stringify(state.workspace)}
            workspace={state.workspace}
          />
        )}
        {tab === "Audit log" && (
          <>
            <H2>Recent workspace activity</H2>
            <DataTable>
              <thead>
                <tr>
                  <Th>Event</Th>
                  <Th>Actor</Th>
                  <Th>Time</Th>
                </tr>
              </thead>
              <tbody>
                {state.audit.map((event) => (
                  <Tr key={event.id}>
                    <Td>{event.event}</Td>
                    <Td>{event.actor}</Td>
                    <Td>{dateLabel(event.at, state.workspace.timezone)}</Td>
                  </Tr>
                ))}
              </tbody>
            </DataTable>
          </>
        )}
      </Panel>
    </>
  );
}
