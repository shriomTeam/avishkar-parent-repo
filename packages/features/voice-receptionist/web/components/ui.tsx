"use client";
import { useState, type ReactNode } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  EmptyState,
  Muted,
  Note,
  PageHeading,
  Panel,
  StatCard,
  StatusBadge,
  SwitchRow,
  TextAreaField,
  TextField,
} from "@clinic/ui";
import { useDemo } from "../lib/demo/provider";
export function Brand() {
  return (
    <a
      className="focus-ring flex items-center gap-[9px] px-[7px] text-[29px] font-[750] tracking-[-1.2px] max-app:text-[24px]"
      href="/voice-receptionist"
    >
      <img
        className="shrink-0 object-contain"
        src="/brand/avishkar-logo.png"
        alt=""
        width={34}
        height={34}
      />
      avishkar
    </a>
  );
}
export { Dialog, Dropdown, Tabs } from "@clinic/ui";
export {
  EmptyState as Empty,
  SwitchRow as Switch,
  TextAreaField as Textarea,
  TextField as Field,
};

/** An error message above or below a form, shown only when there is one. */
export function FormError({ message }: { message?: string }) {
  return message ? <Alert>{message}</Alert> : null;
}
export function Heading({
  title,
  description,
  actions,
  demo = false,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
  demo?: boolean;
}) {
  return (
    <>
      <PageHeading title={title} description={description} actions={actions} />
      {demo && (
        <Note className="mb-[18px]" role="note">
          <strong>Demo section.</strong> This page shows sample data and is not
          connected to real calls yet.
        </Note>
      )}
    </>
  );
}
export function Badge({ children }: { children: string }) {
  const tone = ["Draft", "Unassigned", "Disabled", "Archived"].includes(
    children,
  )
    ? "muted"
    : ["Failed", "Error"].includes(children)
      ? "danger"
      : "brand";
  return <StatusBadge tone={tone}>{children}</StatusBadge>;
}
export function DemoBoundary({ children }: { children: ReactNode }) {
  const { state, error, retry } = useDemo();
  if (!state)
    return (
      <Panel>
        {error ? (
          <>
            <Alert>{error}</Alert>
            <Button variant="outline" onClick={retry}>
              Retry
            </Button>
          </>
        ) : (
          <Muted role="status">Loading demo workspace…</Muted>
        )}
      </Panel>
    );
  return (
    <>
      {error && (
        <Note className="mb-[18px]" role="alert">
          {error}
        </Note>
      )}
      {children}
    </>
  );
}
export function Metric({
  label,
  value,
  sub,
  feature = false,
}: {
  label: string;
  value: string;
  sub: string;
  feature?: boolean;
}) {
  return (
    <StatCard label={label} value={value} hint={sub} highlight={feature} />
  );
}
export function ResetDemo() {
  const { run, busy } = useDemo();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        Reset demo
      </Button>
      {open && (
        <Dialog title="Reset sample workspace?" onClose={() => setOpen(false)}>
          <Muted>
            This clears changes made during this preview and restores the sample
            records.
          </Muted>
          <DialogActions>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="brand"
              disabled={busy}
              onClick={async () => {
                if (await run({ type: "reset" }, "Sample workspace restored"))
                  setOpen(false);
              }}
            >
              Reset demo
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
  );
}
