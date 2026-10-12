"use client";
import type { ReactNode } from "react";
import type { AuthState } from "@/lib/auth/types";
import { DemoProvider } from "@/lib/voice/demo/provider";
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
      <Shell>{children}</Shell>
    </DemoProvider>
  );
}
