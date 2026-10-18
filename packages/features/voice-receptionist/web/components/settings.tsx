"use client";
import { useState } from "react";
import { useDemo } from "../lib/demo/provider";
import { useAuth } from "@clinic/core/web/auth/provider";
import { initials } from "@clinic/core/web/auth/types";
import { SignOut } from "@clinic/core/web/auth/sign-out";
import { dateLabel } from "../lib/format";
import { Heading, Tabs, Select, Switch, Badge, ResetDemo } from "./ui";
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
      <h2>Call data settings</h2>
      <Switch
        label="Store call recordings"
        description="Only enable after reviewing consent and provider agreements."
        checked={privacy.recordCalls}
        onChange={(recordCalls) => setPrivacy({ ...privacy, recordCalls })}
      />
      <div className="formtwo spaced">
        <Select
          label="Transcript retention"
          value={privacy.transcriptRetention}
          onChange={(e) =>
            setPrivacy({ ...privacy, transcriptRetention: e.target.value })
          }
        >
          {["30 days", "90 days", "180 days"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </Select>
        <Select
          label="Recording retention"
          value={privacy.recordingRetention}
          onChange={(e) =>
            setPrivacy({ ...privacy, recordingRetention: e.target.value })
          }
        >
          {["7 days", "30 days", "90 days"].map((x) => (
            <option key={x}>{x}</option>
          ))}
        </Select>
      </div>
      <div className="note">
        These demo preferences do not configure real recording or retention.
        Existing sample call fixtures remain unchanged.
      </div>
      <button className="primary spaced" disabled={busy}>
        Save preferences
      </button>
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
      <section
        className="panel settings-panel"
        aria-label="Your account"
        style={{ marginBottom: 24 }}
      >
        <div className="panelHead" style={{ marginBottom: 0 }}>
          <div className="inline">
            <div className="avatar dark">
              {initials(auth.user.display_name)}
            </div>
            <div>
              <h2>{auth.user.display_name}</h2>
              <small>
                {auth.user.email} · {auth.memberships[0]?.role || "Member"}
              </small>
            </div>
          </div>
          <SignOut />
        </div>
      </section>
      <Tabs
        tabs={["Workspace", "Team", "Privacy & retention", "Audit log"]}
        value={tab}
        onChange={setTab}
      />
      <section
        className="panel settings-panel"
        role="tabpanel"
        aria-label={tab}
      >
        {tab === "Workspace" && (
          <>
            <h2>Workspace details</h2>
            <p className="form-intro">
              Practice information used across your agents.
            </p>
            <div className="summarylist">
              <div>
                <span>Name</span>
                <strong>{auth.workspace?.name}</strong>
              </div>
              <div>
                <span>Timezone</span>
                <strong>{auth.workspace?.timezone}</strong>
              </div>
              <div>
                <span>Callback number</span>
                <strong>{auth.workspace?.phone || "Not set"}</strong>
              </div>
            </div>
            <p className="spaced">
              Workspace details are saved in your account. Editing will be added
              with the workspace management API.
            </p>
          </>
        )}
        {tab === "Team" && (
          <>
            <h2>Workspace team</h2>
            <p>Your actual workspace membership.</p>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Member</th>
                    <th>Role</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>
                      {auth.user.display_name}
                      <small>{auth.user.email}</small>
                    </td>
                    <td>{auth.memberships[0]?.role || "Member"}</td>
                    <td>
                      <Badge>Active</Badge>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
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
            <h2>Recent workspace activity</h2>
            <div className="tablewrap">
              <table>
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>Actor</th>
                    <th>Time</th>
                  </tr>
                </thead>
                <tbody>
                  {state.audit.map((event) => (
                    <tr key={event.id}>
                      <td>{event.event}</td>
                      <td>{event.actor}</td>
                      <td>{dateLabel(event.at, state.workspace.timezone)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>
    </>
  );
}
