"use client";
import { Button, EmptyState, Panel } from "@clinic/ui";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <Panel data-testid="settings-error">
      <EmptyState title="We couldn't load this page" description="Something went wrong. Your settings are safe. Please try again in a moment." />
      <div className="text-center">
        <Button type="button" variant="brand" onClick={reset}>
          Try again
        </Button>
      </div>
    </Panel>
  );
}
