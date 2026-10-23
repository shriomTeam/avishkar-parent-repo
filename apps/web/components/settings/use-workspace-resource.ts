"use client";
import { useEffect, useState } from "react";

/** Abort stale workspace reads and keep failures visible with an explicit retry. */
export function useWorkspaceResource<T>(url: string, enabled: boolean) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const abort = new AbortController();
    fetch(url, {
      signal: abort.signal,
      cache: "no-store",
      credentials: "same-origin",
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(
            response.status === 403
              ? "You don’t have permission to view this information."
              : "Could not load this information. Please retry.",
          );
        const result: T = await response.json();
        if (!abort.signal.aborted) setData(result);
      })
      .catch((cause) => {
        if (!abort.signal.aborted) setError(cause.message);
      });
    return () => abort.abort();
  }, [url, enabled, attempt]);
  return {
    data,
    error,
    retry: () => {
      setData(null);
      setError("");
      setAttempt((value) => value + 1);
    },
  };
}
