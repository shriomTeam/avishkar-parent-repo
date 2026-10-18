"use client";
import type { ReactNode } from "react";
import { useVoiceStatus } from "../lib/voice/provider";

export function VoiceBoundary({ children }: { children: ReactNode }) {
  const { agents, calls, tools, error, retry } = useVoiceStatus();
  if (agents && calls && tools) return <>{children}</>;
  return (
    <div className="panel">
      {error ? (
        <>
          <p role="alert">{error}</p>
          <button onClick={retry}>Retry</button>
        </>
      ) : (
        <p role="status">Loading your voice agents…</p>
      )}
    </div>
  );
}
