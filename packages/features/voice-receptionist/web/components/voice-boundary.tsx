"use client";
import type { ReactNode } from "react";
import { Alert, Button, Muted, Panel } from "@clinic/ui";
import { useVoiceStatus } from "../lib/voice/provider";

export function VoiceBoundary({ children }: { children: ReactNode }) {
  const { agents, calls, tools, error, retry } = useVoiceStatus();
  if (agents && calls && tools) return <>{children}</>;
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
        <Muted role="status">Loading your voice agents…</Muted>
      )}
    </Panel>
  );
}
