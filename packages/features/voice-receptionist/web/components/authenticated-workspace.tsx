"use client";
import type { ReactNode } from "react";
import type { AuthState } from "@clinic/core/web/auth/types";
import { DemoProvider } from "../lib/demo/provider";
import { VoiceDataProvider } from "../lib/voice/provider";
import { Shell } from "./shell";
export function AuthenticatedWorkspace({
  initial,
  children,
}: {
  initial: AuthState;
  children: ReactNode;
}) {
  return (
    <DemoProvider identity={initial}>
      <VoiceDataProvider>
        <Shell>{children}</Shell>
      </VoiceDataProvider>
    </DemoProvider>
  );
}
