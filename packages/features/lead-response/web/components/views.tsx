"use client";
import { useRouter } from "next/navigation";
import { Button, EmptyState, Panel } from "@clinic/ui";

/** Shown to anyone the platform or the API refuses (the API is what enforces it; this only explains). */
export function RoleView() {
  return (
    <Panel data-testid="settings-forbidden">
      <EmptyState
        title="Only the owner or office manager can change these settings"
        description="Ask them if something needs to change. Nothing on this page has been changed."
      />
    </Panel>
  );
}

/** The settings could not be read. Retry asks the server again without leaving the page. */
export function LoadError() {
  const router = useRouter();
  return (
    <Panel data-testid="settings-error">
      <EmptyState title="We couldn't load your settings" description="Nothing has been changed. Check your connection, then try again." />
      <div className="text-center">
        <Button type="button" variant="brand" onClick={() => router.refresh()} data-testid="retry">
          Try again
        </Button>
      </div>
    </Panel>
  );
}
