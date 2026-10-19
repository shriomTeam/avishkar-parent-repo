"use client";
/**
 * The Dormant patients frame: its own sidebar, header bar and footer around the page, in the same layout as the
 * Voice receptionist but written here (nothing is imported from another feature). It is a client component only
 * to know the current path and whether file results are open; the clinic name, the role and whether a saved analysis
 * exists are read on the server and passed in.
 */
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
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
  return (
    <div className="dp-app">
      <a className="dp-skip" href="#main-content">
        Skip to content
      </a>
      <aside className="dp-side">
        <div className="dp-brand">
          <Brand href={ROOT} />
        </div>
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
