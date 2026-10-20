"use client";
/**
 * The Dormant patients frame: its own sidebar, header bar and footer around the page, in the same layout as the
 * Voice receptionist but written here (nothing is imported from another feature). It is a client component only
 * to know the current path and whether file results are open; the clinic name, the role and whether a saved analysis
 * exists are read on the server and passed in.
 *
 * At 901 px and wider the sidebar is fixed. At 900 px and narrower it is a top bar with a Menu button that opens the
 * same content as an inline panel (a disclosure, not a modal, so there is no focus trap): Escape closes it and puts
 * focus back on the button, choosing a link closes it and moves focus to the new page, and opening it moves focus to
 * the first navigation link.
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";
import { SignOut } from "@clinic/core/web/auth/sign-out";
import { Brand } from "@clinic/ui";

import { clinicOf, personOf, roleLabel } from "../lib/profile";
import { canRunRole } from "../lib/roles";
import { useCsvResult } from "./csv-provider";
import { Icon, type IconName } from "./kit";
import { DATA_NAV, NAV, ROOT, activeHref, breadcrumb } from "./shell-nav";
import { showingFile, statusOf, type Saved } from "./shell-status";

export function Shell({
  clinicName,
  role: serverRole,
  saved,
  children,
}: {
  clinicName: string | null;
  role: string | null;
  saved: Saved;
  children: ReactNode;
}) {
  const path = usePathname();
  const params = useSearchParams();
  const { auth } = useAuth();
  const { result } = useCsvResult();
  const role = auth.memberships.find((m) => m.workspace_id === auth.workspace?.id)?.role;
  const active = activeHref(path);
  const trail = breadcrumb(path);
  const clinic = clinicOf(clinicName);
  const person = personOf(auth.user);
  const roleText = roleLabel(serverRole);
  const status = statusOf(saved, showingFile(path, params.get("view"), params.get("source"), !!result));

  const [open, setOpen] = useState(false);
  const panelId = useId();
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const opened = useRef(false); // focus moves only when the person opens the menu, never on first render

  useEffect(() => {
    if (open && opened.current) panel.current?.querySelector<HTMLElement>(".dp-nav a")?.focus();
  }, [open]);
  // a link inside the panel was chosen, or the page changed some other way: close, and leave focus on the new page
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
    if (focus === "button") button.current?.focus();
    if (focus === "page") requestAnimationFrame(() => document.getElementById("main-content")?.focus({ preventScroll: true }));
  }
  return (
    <div className="dp-app">
      <a className="dp-skip" href="#main-content">
        Skip to content
      </a>
      <aside
        className="dp-side"
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation();
            close("button");
          }
        }}
      >
        <div className="dp-sidehead">
          <div className="dp-brand">
            <Brand href={ROOT} />
          </div>
          <button
            ref={button}
            type="button"
            className="dp-menu-btn"
            aria-expanded={open}
            aria-controls={panelId}
            onClick={toggle}
            data-testid="menu-button"
          >
            <Icon name={open ? "close" : "menu"} size={18} />
            Menu
          </button>
        </div>
        <div
          id={panelId}
          ref={panel}
          className="dp-panel"
          data-open={open}
          onClick={(e) => {
            if ((e.target as HTMLElement).closest("a")) close("page");
          }}
        >
          <div className="dp-workspace">
            <div className="dp-avatar" aria-hidden>
              {clinic.letter}
            </div>
            <div>
              <strong data-testid="clinic-name">{clinic.name}</strong>
              <small>Dormant patients workspace</small>
            </div>
          </div>
          <Link className="dp-return" href="/">
            ← All clinic products
          </Link>
          <div className="dp-navlabel">WORKSPACE</div>
          <NavList label="Dormant patients sections" items={NAV} active={active} />
          {canRunRole(role) && (
            <>
              <div className="dp-navlabel">DATA</div>
              <NavList label="Dormant patients data" items={DATA_NAV} active={active} />
            </>
          )}
          <div className="dp-sidebottom">
            <div className="dp-status" data-mode={status.tone} data-testid="status-card">
              <strong>{status.title}</strong>
              <p>{status.text}</p>
            </div>
            <div className="dp-profile" data-testid="profile">
              <div className="dp-avatar dp-avatar-dark" aria-hidden>
                {person.initials}
              </div>
              <div>
                <strong data-testid="profile-name">{person.name}</strong>
                {roleText && <small data-testid="profile-role">{roleText}</small>}
              </div>
            </div>
            <div className="dp-signout">
              <SignOut />
            </div>
          </div>
        </div>
      </aside>
      <div className="dp-frame">
        <header className="dp-header">
          <nav aria-label="Breadcrumb" className="dp-crumbs">
            {trail.map((part, i) => (
              <span key={part} aria-current={i === trail.length - 1 ? "page" : undefined}>
                {i > 0 && <Icon name="chevron" size={13} />}
                {i === trail.length - 1 ? <strong>{part}</strong> : part}
              </span>
            ))}
          </nav>
          <span className="dp-mode" data-mode={status.tone} data-testid="mode-badge">
            {status.badge}
          </span>
        </header>
        <main id="main-content" tabIndex={-1} className="dp-main">
          <div className="dp-page">{children}</div>
        </main>
        <footer className="dp-footer" data-testid="shell-footer">
          Avishkar Dormant patients · {status.footer}
        </footer>
      </div>
    </div>
  );
}

function NavList({
  label,
  items,
  active,
}: {
  label: string;
  items: { href: string; label: string; icon: IconName }[];
  active: string | null;
}) {
  return (
    <nav aria-label={label} className="dp-nav">
      {items.map((item) => (
        <Link key={item.href} href={item.href} aria-current={active === item.href ? "page" : undefined}>
          <Icon name={item.icon} size={19} />
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
