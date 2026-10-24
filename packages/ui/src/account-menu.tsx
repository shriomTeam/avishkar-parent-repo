"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ChevronsUpDown, LogOut, Settings } from "lucide-react";
import { Avatar } from "./layout";
import { Alert } from "./layout";

/** Shared account disclosure. Hosts own authentication and the Settings destination. */
export function AccountMenu({
  name,
  email,
  role,
  initials,
  settingsHref = "/settings",
  onSignOut,
}: {
  name: string;
  email: string;
  role: string;
  initials: string;
  settingsHref?: string;
  onSignOut: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    panel.current?.querySelector<HTMLElement>("a")?.focus();
    const outside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  return (
    <div
      ref={root}
      className="relative min-w-0"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          setOpen(false);
          trigger.current?.focus();
        }
      }}
    >
      {open && (
        <div
          ref={panel}
          id={id}
          aria-label="Account actions"
          className="absolute bottom-full left-0 z-50 mb-2 w-full min-w-[200px] rounded-xl border border-line bg-white p-2 shadow-[0_12px_40px_#201d1d20]"
        >
          <div className="border-b border-line px-3 py-3">
            <p className="truncate text-[13px] font-semibold">{name}</p>
            <p className="mt-1 truncate text-[11px] text-muted">{email}</p>
          </div>
          <a
            href={settingsHref}
            className="focus-ring my-1 flex items-center gap-3 rounded-lg px-3 py-3 text-[13px] hover:bg-brand-soft"
            onClick={() => setOpen(false)}
          >
            <Settings size={17} aria-hidden="true" />
            Settings
          </a>
          <div className="border-t border-line pt-1">
            <button
              type="button"
              disabled={busy}
              className="focus-ring flex w-full cursor-pointer items-center gap-3 rounded-lg px-3 py-3 text-left text-[13px] text-danger-ink hover:bg-danger-soft disabled:opacity-50"
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await onSignOut();
                } catch {
                  setError("Could not sign out. Please retry.");
                  setBusy(false);
                }
              }}
            >
              <LogOut size={17} aria-hidden="true" />
              {busy ? "Signing out…" : "Sign out"}
            </button>
          </div>
          {error && <Alert>{error}</Alert>}
        </div>
      )}
      <button
        type="button"
        ref={trigger}
        aria-label={`Account menu for ${name}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        className="focus-ring flex w-full cursor-pointer items-center gap-3 rounded-xl border border-line bg-white p-2.5 text-left hover:bg-canvas"
        onClick={() => setOpen((value) => !value)}
      >
        <Avatar tone="dark">{initials}</Avatar>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12px] font-semibold">
            {name}
          </span>
          <span className="mt-1 block truncate text-[11px] text-muted capitalize">
            Workspace {role.replaceAll("_", " ")}
          </span>
        </span>
        <ChevronsUpDown
          size={15}
          className="shrink-0 text-muted"
          aria-hidden="true"
        />
      </button>
    </div>
  );
}
