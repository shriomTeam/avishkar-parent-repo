"use client";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { usePathname } from "next/navigation";
import type { AuthState } from "./types";
const Context = createContext<{
  auth: AuthState;
  refresh: () => Promise<AuthState>;
  write: (path: string, body?: unknown) => Promise<Response>;
} | null>(null);
export function AuthProvider({
  initial,
  children,
}: {
  initial: AuthState;
  children: ReactNode;
}) {
  const [auth, setAuth] = useState(initial);
  const [error, setError] = useState(false);
  const [expired, setExpired] = useState(false);
  const path = usePathname();
  // Only the newest session check may change what the user sees; an older, slower answer must not undo it.
  const latest = useRef(0);
  function selectionChanged(next: AuthState) {
    const beforeRole = initial.memberships.find(
      (m) => m.workspace_id === initial.workspace?.id,
    )?.role;
    const afterRole = next.memberships.find(
      (m) => m.workspace_id === next.workspace?.id,
    )?.role;
    if (
      next.workspace?.id !== initial.workspace?.id ||
      beforeRole !== afterRole
    ) {
      setExpired(true);
      window.location.replace(
        next.workspace
          ? "/"
          : next.memberships.length
            ? "/workspaces"
            : "/onboarding",
      );
      return true;
    }
    return false;
  }
  async function refresh() {
    const id = ++latest.current;
    const response = await fetch("/api/v1/auth/me", {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (response.status === 401) {
      setExpired(true);
      window.location.replace("/login");
      throw new Error("Please sign in again.");
    }
    if (!response.ok)
      throw new Error("Could not check your session. Please retry.");
    const next: AuthState = await response.json();
    if (next.user.id !== initial.user.id) {
      setExpired(true);
      window.location.replace(next.needs_onboarding ? "/onboarding" : "/");
      throw new Error("Your signed-in account changed.");
    }
    if (id === latest.current) {
      if (selectionChanged(next)) throw new Error("Workspace access changed.");
      setAuth(next);
      setError(false);
    }
    return next;
  }
  useEffect(() => {
    let live = true;
    const check = () => {
      const id = ++latest.current;
      fetch("/api/v1/auth/me", {
        cache: "no-store",
        credentials: "same-origin",
      })
        .then(async (response) => {
          if (!live || id !== latest.current) return;
          if (response.status === 401) {
            setExpired(true);
            window.location.replace("/login");
            return;
          }
          if (!response.ok) throw new Error();
          const next: AuthState = await response.json();
          if (live && id === latest.current) {
            if (next.user.id !== initial.user.id) {
              setExpired(true);
              window.location.replace(
                next.needs_onboarding ? "/onboarding" : "/",
              );
              return;
            }
            if (selectionChanged(next)) return;
            setAuth(next);
            setError(false);
          }
        })
        .catch(() => {
          if (live && id === latest.current) setError(true);
        });
    };
    check();
    window.addEventListener("focus", check);
    const timer = setInterval(check, 60000);
    return () => {
      live = false;
      clearInterval(timer);
      window.removeEventListener("focus", check);
    };
  }, [path, initial.user.id]);
  async function write(url: string, body?: unknown) {
    const response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": auth.csrf_token,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (response.status === 401) {
      setExpired(true);
      window.location.replace("/login");
      throw new Error("Please sign in again.");
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      // Only expose known application errors, never arbitrary server diagnostics.
      const messages: Record<string, string> = {
        member_already_exists_or_requires_review:
          "This email already belongs to a workspace member. Manage their existing access in Workspace members instead.",
        invitation_already_pending:
          "An invitation is already pending for this email. Use Resend in Invitations to send a new link.",
        invalid_email: "Enter a valid email address.",
        invitations_not_configured:
          "Email invitations are not configured for this environment yet.",
        resend_cooldown: "Wait one minute before resending this invitation.",
        invitation_not_pending:
          "This invitation is no longer pending. Refresh to see its current status.",
      };
      const detail = typeof payload?.detail === "string" ? payload.detail : "";
      throw new Error(
        messages[detail] ??
          (response.status === 403
            ? "Your session could not authorize this action. Refresh and retry."
            : response.status === 429
              ? "Too many attempts. Please wait before retrying."
              : "Could not save this change. Please retry."),
      );
    }
    return response;
  }
  if (expired) return <p role="status">Returning to sign-in…</p>;
  if (error)
    return (
      <main className="mx-auto max-w-[700px] px-[30px] py-[70px]">
        <h1 className="mb-[5px] text-[30px] font-[650] tracking-[-1px]">
          Unable to check your session
        </h1>
        <p className="my-[7px] text-[14px] text-muted">
          The authentication service is unavailable. Your dashboard is hidden
          until it can be verified.
        </p>
        <button
          className="cursor-pointer rounded-[9px] border border-line bg-white px-4 py-2.5 text-[14px] font-semibold text-ink hover:border-brand"
          onClick={() => {
            void refresh().catch(() => setError(true));
          }}
        >
          Retry
        </button>
      </main>
    );
  return (
    <Context.Provider value={{ auth, refresh, write }}>
      {children}
    </Context.Provider>
  );
}
export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error("AuthProvider required");
  return value;
}
