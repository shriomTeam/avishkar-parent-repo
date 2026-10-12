"use client";
import { useState } from "react";
import { useAuth } from "@/lib/auth/provider";
export function SignOut() {
  const { write } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div>
      <button
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
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
    </div>
  );
}
