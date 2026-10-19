"use client";
/**
 * The Dormant patients frame: its own sidebar, header bar and footer around the page, in the same layout as the
 * Voice receptionist but written here (nothing is imported from another feature). It is a client component only
 * to know the current path; the clinic name and role are read on the server and passed in.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";
import { Brand } from "@clinic/ui";

import { Icon, type IconName } from "./kit";
import { canRunRole } from "../lib/roles";
import { DATA_NAV, NAV, ROOT, activeHref, breadcrumb } from "./shell-nav";

export function Shell({ clinicName, children }: { clinicName: string; children: ReactNode }) {
  const path = usePathname();
  const { auth } = useAuth();
  const role = auth.memberships.find((m) => m.workspace_id === auth.workspace?.id)?.role;
  const active = activeHref(path);
  const trail = breadcrumb(path);
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
            {clinicName.trim()[0]?.toUpperCase() ?? "D"}
          </div>
          <div>
            <strong data-testid="clinic-name">{clinicName}</strong>
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
        </header>
        <main id="main-content" tabIndex={-1} className="dp-main">
          <div className="dp-page">{children}</div>
        </main>
        <footer className="dp-footer">Avishkar Dormant patients</footer>
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
