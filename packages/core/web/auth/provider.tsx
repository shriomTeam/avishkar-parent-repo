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
    if (!response.ok)
      throw new Error(
        response.status === 403
          ? "Your session could not authorize this action. Refresh and retry."
          : "Could not save this change. Please retry.",
      );
    return response;
  }
  if (expired) return <p role="status">Returning to sign-in…</p>;
  if (error)
    return (
      <main className="standalone">
        <h1>Unable to check your session</h1>
        <p>
          The authentication service is unavailable. Your dashboard is hidden
          until it can be verified.
        </p>
        <button
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
