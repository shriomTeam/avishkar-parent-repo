"use client";
import type { ReactNode } from "react";
import { Alert, Button, Panel } from "@clinic/ui";
import { useVoiceStatus } from "../lib/voice/provider";
import { PageSkeleton } from "./skeletons";

/** Shows `fallback` (the screen's own skeleton) while the workspace loads, an error with Retry if it fails. */
export function VoiceBoundary({
  children,
  fallback = <PageSkeleton />,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const { agents, calls, tools, variables, error, retry } = useVoiceStatus();
  if (agents && calls && tools && variables) return <>{children}</>;
  if (!error) return <>{fallback}</>;
  return (
    <Panel>
      <Alert>{error}</Alert>
      <Button variant="outline" onClick={retry}>
        Retry
      </Button>
    </Panel>
  );
}
