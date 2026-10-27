"use client";
import { useState } from "react";
import { Alert, Button, Dropdown } from "@clinic/ui";
import { useAuth } from "@/lib/auth/provider";
export function WorkspaceSwitcher() {
  const { auth, write } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (auth.memberships.length < 2) return null;
  return (
    <div className="mb-4">
      <Dropdown
        label="Switch workspace"
        flush
        value={auth.workspace?.id ?? ""}
        disabled={busy}
        options={[
          ...(!auth.workspace
            ? [{ value: "", label: "Choose workspace" }]
            : []),
          ...auth.memberships.map((m) => ({
            value: m.workspace_id,
            label: m.workspace.name,
          })),
        ]}
        onChange={(value) => {
          if (!value) return;
          setBusy(true);
          setError("");
          void write("/api/v1/auth/workspace", { workspace_id: value })
            .then(() => window.location.replace("/"))
            .catch(() => {
              setBusy(false);
              setError("Could not switch workspace. Please retry.");
            });
        }}
      />
      {error && <Alert>{error}</Alert>}
    </div>
  );
}
export function WorkspaceChoices() {
  const { auth, write } = useAuth();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <div className="grid gap-3">
      {auth.memberships.map((m) => (
        <Button
          key={m.workspace_id}
          variant="outline"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void write("/api/v1/auth/workspace", {
              workspace_id: m.workspace_id,
            })
              .then(() => window.location.replace("/"))
              .catch(() => {
                setError("Could not select workspace.");
                setBusy(false);
              });
          }}
        >
          {m.workspace.name}
        </Button>
      ))}
      {error && <Alert>{error}</Alert>}
    </div>
  );
}
