"use client";
import { Button, Muted } from "@clinic/ui";
import { StandalonePage } from "../components/standalone-page";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <StandalonePage title="Unable to load your workspace">
      <Muted>The service is temporarily unavailable. Please retry.</Muted>
      <Button variant="brand" onClick={reset}>
        Try again
      </Button>
    </StandalonePage>
  );
}
