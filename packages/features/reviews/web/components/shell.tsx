"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brand } from "@clinic/ui";
import { SignOut } from "@clinic/core/web/auth/sign-out";
import { useAuth } from "@clinic/core/web/auth/provider";
import { initials } from "@clinic/core/web/auth/types";

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

const navigation = [
  { href: "/reviews", name: "Overview", d: "M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1z" },
  { href: "/reviews#google", name: "Google profile", d: "m12 3 2.4 5.7L20.5 9.5l-4.4 3.8 1.3 6.2L12 16.8 6.6 19.5l1.3-6.2L3.5 9.5l6.1-.8z" },
  { href: "/reviews#campaigns", name: "Campaigns", d: "M4 10v4l12 6V4zM16 9.5v5M19 8a6 6 0 0 1 0 8" },
  { href: "/reviews#follow-ups", name: "Follow-ups", d: "M4 6h16v10H7l-3 3z" },
];

export function ReviewsShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { auth } = useAuth();
  const clinic = auth.workspace?.name || "Reviews workspace";
  const role =
    auth.memberships.find((member) => member.workspace.id === auth.workspace?.id)?.role ||
    auth.memberships[0]?.role ||
    "Member";

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Brand href="/reviews" />
        <div className="workspace">
          <div className="avatar">{clinic[0] || "R"}</div>
          <div>
            <strong>{clinic}</strong>
            <small>Reviews workspace</small>
          </div>
        </div>
        <Link className="platform-return" href="/">
          ← All clinic products
        </Link>
        <div className="navlabel">WORKSPACE</div>
        <nav aria-label="Workspace navigation">
          {navigation.map(({ href, name, d }) => {
            const active = href === "/reviews" && pathname === "/reviews";
            return (
              <Link key={href} href={href} className={active ? "active" : ""} aria-current={active ? "page" : undefined}>
                <Icon d={d} />
                {name}
              </Link>
            );
          })}
        </nav>
        <div className="sidebottom">
          <div className="profile">
            <div className="avatar dark">{initials(auth.user.display_name)}</div>
            <div>
              <strong>{auth.user.display_name}</strong>
              <small>{role}</small>
            </div>
          </div>
          <SignOut />
        </div>
      </aside>
      <div className="shell">
        <header>
          <span className="breadcrumb">
            Workspace{" "}
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
              <path d="m9 6 6 6-6 6" />
            </svg>{" "}
            <strong>Reviews</strong>
          </span>
          <div className="headerRight">
            <span className="badge pale">4–5 stars go to Google</span>
          </div>
        </header>
        <main id="main-content">{children}</main>
        <footer>Avishkar Reviews</footer>
      </div>
    </>
  );
}
