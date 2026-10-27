"use client";
import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Brand,
  Button,
  Panel,
  StatusBadge,
  TextField,
  buttonStyles,
} from "@clinic/ui";
import type { AuthState } from "@/lib/auth/types";

type Preview = {
  workspace_name: string;
  role: string;
  email: string;
  needs_verification: boolean;
};
const errors: Record<string, string> = {
  invitation_wrong_account:
    "This invitation is for a different email address. Switch to the invited Google account.",
  invitation_expired_or_invalid:
    "This invitation has expired, was revoked, or has already been used. Ask your workspace administrator for a new invitation.",
  invitation_no_longer_available:
    "This invitation is no longer available. Contact the workspace owner.",
  recent_login_required: "Please sign in again to accept this invitation.",
  mailbox_verification_required:
    "Enter the verification code sent to your invited email.",
  rate_limited: "Too many attempts. Please wait before trying again.",
  member_already_exists:
    "You already belong to this workspace. Return to the app and choose your workspace.",
  membership_requires_review:
    "This membership requires the original Google account. Sign in with that account or contact the workspace owner.",
  role_grant_denied:
    "The inviter can no longer restore this membership with the requested role. Ask the workspace owner for a new invitation.",
  invitations_not_configured:
    "Invitations are not configured for this environment yet.",
};
export function InvitationAcceptance({
  initial,
}: {
  initial: AuthState | null;
}) {
  const [auth] = useState(initial);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  async function request(path: string, body?: unknown) {
    const response = await fetch(`/api/v1/invitations/${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        ...(auth ? { "X-CSRF-Token": auth.csrf_token } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        errors[data.detail] ??
          "Could not complete this request. Please try again.",
      );
    return data;
  }
  const initialization = useRef<Promise<Preview | null> | null>(null);
  useEffect(() => {
    let live = true;
    if (!initialization.current) {
      const token = new URLSearchParams(window.location.hash.slice(1)).get(
        "token",
      );
      if (token) window.history.replaceState(null, "", "/invite");
      initialization.current = (async () => {
        if (token) await request("context", { token });
        return auth ? ((await request("current")) as Preview) : null;
      })();
    }
    void initialization.current
      .then((data) => {
        if (live) {
          setPreview(data);
          setReady(true);
        }
      })
      .catch((cause) => {
        if (live) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Unable to load invitation.",
          );
          setReady(true);
        }
      });
    return () => {
      live = false;
    };
    // Auth is the fixed entry snapshot; account changes navigate to a new page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const action = async (name: string, body: unknown) => {
    setBusy(true);
    setError("");
    try {
      await request(name, body);
      if (name === "accept") window.location.replace("/");
      else setSent(true);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not complete request.",
      );
    } finally {
      setBusy(false);
    }
  };
  const switchAccount = async () => {
    if (auth)
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": auth.csrf_token },
      });
    window.location.replace("/api/v1/auth/google/login");
  };
  return (
    <main className="min-h-dvh bg-canvas px-5 py-14 font-brand text-ink">
      <div className="mx-auto max-w-xl">
        <div className="mb-8">
          <Brand />
        </div>
        <Panel>
          <StatusBadge>Workspace invitation</StatusBadge>
          <h1 className="mt-5 mb-3 text-3xl font-semibold tracking-tight">
            {preview
              ? `Join ${preview.workspace_name}`
              : "Join your team on Avishkar"}
          </h1>
          {error && <Alert>{error}</Alert>}
          {!ready ? (
            <p role="status">Checking your invitation…</p>
          ) : !auth ? (
            <>
              <p className="mb-6 text-sm leading-6 text-muted">
                Sign in with the email address that received the invitation.
                You’ll review your workspace and role before joining.
              </p>
              <a
                href="/api/v1/auth/google/login"
                className={buttonStyles("brand")}
              >
                Continue with Google
              </a>
            </>
          ) : preview ? (
            <>
              <p className="mb-5 text-sm leading-6 text-muted">
                You’re signed in as <strong>{auth.user.email}</strong>. You’ll
                join this existing workspace as{" "}
                <strong className="capitalize">
                  {preview.role.replaceAll("_", " ")}
                </strong>
                .
              </p>
              {preview.needs_verification && (
                <div className="my-5">
                  <p className="mb-3 text-sm text-muted">
                    Verify access to your invited mailbox before joining.
                  </p>
                  <Button
                    variant="outline"
                    disabled={busy}
                    onClick={() => void action("verification", {})}
                  >
                    {sent
                      ? "Resend verification code"
                      : "Send verification code"}
                  </Button>
                  {sent && (
                    <>
                      <p role="status" className="my-3 text-sm text-brand-ink">
                        Verification email queued. Check your inbox.
                      </p>
                      <TextField
                        label="Verification code"
                        inputMode="numeric"
                        maxLength={6}
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                      />
                    </>
                  )}
                </div>
              )}
              <Button
                variant="brand"
                disabled={
                  busy || (preview.needs_verification && code.length !== 6)
                }
                onClick={() =>
                  void action("accept", { verification_code: code || null })
                }
              >
                {busy ? "Please wait…" : "Accept invitation"}
              </Button>
            </>
          ) : (
            <p className="text-sm text-muted">
              Your invitation cannot be accepted with this account or link.
            </p>
          )}
          {auth && (
            <div className="mt-6 flex flex-wrap gap-3">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  void switchAccount().catch(() =>
                    setError("Could not switch account. Please retry."),
                  )
                }
              >
                Switch Google account
              </Button>
              <Button
                variant="outline"
                onClick={() => {
                  void request("dismiss", {})
                    .then(() => window.location.replace("/"))
                    .catch(() =>
                      setError("Could not leave invitation. Please retry."),
                    );
                }}
              >
                Return to app
              </Button>
            </div>
          )}
        </Panel>
      </div>
    </main>
  );
}
