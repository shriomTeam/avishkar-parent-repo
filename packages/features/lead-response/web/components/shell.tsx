"use client";
/**
 * The Lead response frame: its own sidebar, header bar and footer around the page, written here (nothing is imported
 * from another feature). The sidebar lists one section, Settings; the task list arrives with the staff dashboard and
 * will be the first item then.
 *
 * Wide screens: a fixed sidebar. At 700 px and narrower the sidebar is a top bar with a Menu button that opens the
 * same content as an inline panel (a disclosure, not a modal, so there is no focus trap): Escape closes it and puts
 * focus back on the button, choosing a link closes it, and opening it moves focus to the first link.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";
import { SignOut } from "@clinic/core/web/auth/sign-out";
import { Button } from "@clinic/ui";

import { FOCUS, LINK, SCOPE } from "../lib/look";
import { clinicOf, personOf, roleLabel } from "../lib/profile";

export const ROOT = "/lead-response";
export const SETTINGS_PATH = `${ROOT}/settings`;

export function Shell({ role, children }: { role: string | null; children: ReactNode }) {
  const path = usePathname();
  const { auth } = useAuth();
  const clinic = clinicOf(auth.workspace?.name);
  const person = personOf(auth.user);
  const roleText = roleLabel(role);
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const menuBox = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const opened = useRef(false); // focus moves only when the person opens the menu, never on first render

  useEffect(() => {
    if (open && opened.current) panel.current?.querySelector<HTMLElement>("nav a")?.focus();
  }, [open]);
  useEffect(() => {
    setOpen(false);
  }, [path]);

  function toggle() {
    opened.current = !open;
    setOpen(!open);
  }
  function close(focus: "button" | "page" | null) {
    opened.current = false;
    setOpen(false);
    if (focus === "button") menuBox.current?.querySelector("button")?.focus();
    if (focus === "page") requestAnimationFrame(() => document.getElementById("main-content")?.focus({ preventScroll: true }));
  }

  return (
    <div className={`${SCOPE} min-h-dvh bg-[#fafaf9] font-brand text-[15px] leading-normal text-ink app:grid app:grid-cols-[260px_minmax(0,1fr)]`}>
      <a
        href="#main-content"
        className={`${FOCUS} sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2`}
      >
        Skip to content
      </a>
      <aside
        className="border-line bg-white max-app:border-b app:sticky app:top-0 app:h-dvh app:overflow-y-auto app:border-r"
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation();
            close("button");
          }
        }}
      >
        <div className="flex items-center justify-between gap-3 px-5 py-4">
          <Link href={ROOT} className={`${FOCUS} flex items-center gap-2.5 rounded-lg text-[18px] font-bold tracking-[-0.4px]`}>
            <img src="/brand/avishkar-logo.png" alt="" width={34} height={34} />
            avishkar
          </Link>
          <div className="app:hidden" ref={menuBox}>
            <Button
              type="button"
              variant="outline"
              aria-expanded={open}
              aria-controls={panelId}
              onClick={toggle}
              data-testid="menu-button"
            >
              {open ? "Close menu" : "Menu"}
            </Button>
          </div>
        </div>
        <div
          id={panelId}
          ref={panel}
          className={`${open ? "block" : "max-app:hidden"} px-5 pb-5`}
          data-testid="menu-panel"
          onClick={(e) => {
            if ((e.target as HTMLElement).closest("a")) close("page");
          }}
        >
          <div className="mb-4 flex items-center gap-3 rounded-[13px] border border-line p-3">
            <div aria-hidden className="grid size-9 shrink-0 place-items-center rounded-lg bg-brand-soft font-bold text-brand-ink">
              {clinic.letter}
            </div>
            <div className="min-w-0">
              <strong className="block truncate" data-testid="clinic-name">
                {clinic.name}
              </strong>
              <small className="text-muted">Lead response</small>
            </div>
          </div>
          <Link href="/" className={`${LINK} mb-5 inline-block text-[14px]`}>
            ← All clinic products
          </Link>
          <div className="mb-2 text-[12px] font-semibold tracking-wide text-muted">WORKSPACE</div>
          <nav aria-label="Lead response sections" className="mb-6">
            <Link
              href={SETTINGS_PATH}
              aria-current={path === SETTINGS_PATH ? "page" : undefined}
              className={`${FOCUS} flex items-center gap-2.5 rounded-lg border-l-4 border-transparent px-3 py-2.5 font-medium aria-[current=page]:border-[#2f6b10] aria-[current=page]:bg-brand-soft aria-[current=page]:font-bold aria-[current=page]:text-brand-ink`}
            >
              Settings
            </Link>
          </nav>
          <div className="border-t border-line pt-4" data-testid="profile">
            <div className="mb-2 flex items-center gap-3">
              <div aria-hidden className="grid size-9 shrink-0 place-items-center rounded-full bg-ink text-[13px] font-semibold text-white">
                {person.initials}
              </div>
              <div className="min-w-0">
                <strong className="block truncate" data-testid="profile-name">
                  {person.name}
                </strong>
                {roleText && (
                  <small className="text-muted" data-testid="profile-role">
                    {roleText}
                  </small>
                )}
              </div>
            </div>
            <SignOut className={`${FOCUS} cursor-pointer rounded-lg border border-line px-3 py-2 text-[14px] font-semibold`} />
          </div>
        </div>
      </aside>
      <div className="flex min-h-dvh min-w-0 flex-col">
        <header className="border-line border-b bg-white px-6 py-3.5 text-[14px] max-app:px-4">
          <nav aria-label="Breadcrumb">
            <span className="text-muted">Workspace</span>
            <span aria-hidden className="mx-2 text-muted">
              ›
            </span>
            <strong aria-current="page">Settings</strong>
          </nav>
        </header>
        <main id="main-content" tabIndex={-1} className="min-w-0 flex-1 px-6 py-6 outline-none max-app:px-4">
          <div className="mx-auto max-w-[820px]">{children}</div>
        </main>
        <footer className="border-line border-t px-6 py-3 text-[13px] text-muted max-app:px-4" data-testid="shell-footer">
          Avishkar Lead response
        </footer>
      </div>
    </div>
  );
}
