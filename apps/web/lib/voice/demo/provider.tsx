"use client";
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { AuthState } from "@/lib/auth/types";
import { useCallback } from "react";
import type { DemoCommand, DemoState } from "@/lib/voice/types";
import { mockDashboardService } from "@/lib/voice/services/mock-dashboard";
const Context = createContext<{
  state: DemoState | null;
  run: (command: DemoCommand, message?: string) => Promise<boolean>;
  notify: (message: string) => void;
  busy: boolean;
  error: string | null;
  retry: () => void;
} | null>(null);
// State intentionally lasts until refresh; no browser persistence/authentication claim.
export function DemoProvider({
  children,
  identity,
}: {
  children: ReactNode;
  identity: AuthState;
}) {
  const normalize = useCallback(
    (sample: DemoState): DemoState => ({
      ...sample,
      workspace: {
        ...sample.workspace,
        name: identity.workspace?.name || "",
        timezone: identity.workspace?.timezone || "UTC",
        phone: identity.workspace?.phone || "",
        address: "",
      },
      variables: sample.variables.map((v) =>
        v.name === "company_name"
          ? { ...v, value: identity.workspace?.name || "" }
          : v,
      ),
      audit: sample.audit.map((event) => ({ ...event, actor: "Sample actor" })),
    }),
    [identity],
  );
  const [state, setState] = useState<DemoState | null>(null);
  const current = useRef<DemoState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState("");
  const lock = useRef(false);
  const load = () => {
    setError(null);
    mockDashboardService
      .load()
      .then((s) => {
        current.current = normalize(s);
        setState(current.current);
      })
      .catch(() =>
        setError("Could not load the demo workspace. Please retry."),
      );
  };
  useEffect(() => {
    let cancelled = false;
    mockDashboardService
      .load()
      .then((s) => {
        if (!cancelled) {
          current.current = normalize(s);
          setState(current.current);
        }
      })
      .catch(() => {
        if (!cancelled)
          setError("Could not load the demo workspace. Please retry.");
      });
    return () => {
      cancelled = true;
    };
  }, [normalize]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 3500);
    return () => clearTimeout(timer);
  }, [toast]);
  async function run(command: DemoCommand, message = "Saved in this demo") {
    if (lock.current || !current.current) return false;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      let next = await mockDashboardService.execute(current.current, command);
      if (command.type === "reset") next = normalize(next);
      else
        next = {
          ...next,
          audit: next.audit.map((event, index) =>
            index === 0
              ? { ...event, actor: identity.user.display_name }
              : event,
          ),
        };
      current.current = next;
      setState(next);
      setToast(message);
      return true;
    } catch {
      setError("The change could not be saved. Please try again.");
      return false;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Context.Provider
      value={{ state, run, notify: setToast, busy, error, retry: load }}
    >
      {children}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </Context.Provider>
  );
}
export function useDemo() {
  const value = useContext(Context);
  if (!value) throw new Error("DemoProvider is required");
  return value;
}
