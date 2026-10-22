"use client";
import { useState } from "react";
import { useAuth } from "./provider";
export function SignOut({
  className,
  errorClassName = "my-3 rounded-lg bg-danger-soft px-3.5 py-2.5 text-danger-ink",
}: {
  className?: string;
  errorClassName?: string;
} = {}) {
  const { write } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div>
      <button
        className={className}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await write("/api/v1/auth/logout");
            window.location.replace("/login");
          } catch (error) {
            setError(
              error instanceof Error ? error.message : "Could not sign out.",
            );
            setBusy(false);
          }
        }}
      >
        {busy ? "Signing out…" : "Sign out"}
      </button>
      {error && (
        <p role="alert" className={errorClassName}>
          {error}
        </p>
      )}
    </div>
  );
}
