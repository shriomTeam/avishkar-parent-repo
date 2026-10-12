"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Bot,
  Phone,
  List,
  Mic,
  Code,
  Brackets,
  Settings,
  ChevronRight,
} from "lucide-react";
import { Brand, DemoBoundary } from "./ui";
import { useAuth } from "@/lib/auth/provider";
import { initials } from "@/lib/auth/types";
import { useDemo } from "@/lib/voice/demo/provider";
export const navigation = [
  { path: "/voice-receptionist", name: "Overview", icon: LayoutDashboard },
  { path: "/voice-receptionist/agents", name: "Voice agents", icon: Bot },
  { path: "/voice-receptionist/numbers", name: "Phone numbers", icon: Phone },
  { path: "/voice-receptionist/calls", name: "Call history", icon: List },
  { path: "/voice-receptionist/test", name: "Test studio", icon: Mic },
  { path: "/voice-receptionist/tools", name: "Tools", icon: Code },
  { path: "/voice-receptionist/variables", name: "Variables", icon: Brackets },
  { path: "/voice-receptionist/settings", name: "Settings", icon: Settings },
];
export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { state } = useDemo();
  const { auth } = useAuth();
  const active = navigation.find((item) =>
    item.path === "/voice-receptionist"
      ? pathname === item.path
      : pathname.startsWith(item.path),
  );
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="sidebar">
        <Brand />
        <div className="workspace">
          <div className="avatar">{state?.workspace.name[0] || "B"}</div>
          <div>
            <strong data-testid="clinic-name">
              {state?.workspace.name || "Voice workspace"}
            </strong>
            <small>Voice workspace</small>
          </div>
        </div>
        <Link className="platform-return" href="/">
          ← All clinic products
        </Link>
        <div className="navlabel">WORKSPACE</div>
        <nav aria-label="Workspace navigation">
          {navigation.map(({ path, name, icon: Icon }) => (
            <Link
              key={path}
              href={path}
              className={active?.path === path ? "active" : ""}
              aria-current={active?.path === path ? "page" : undefined}
            >
              <Icon size={19} />
              {name}
            </Link>
          ))}
        </nav>
        <div className="sidebottom">
          <div className="pilot">
            <strong>Authenticated workspace</strong>
            <p>Sample data · simulated actions</p>
          </div>
          <Link className="profile" href="/voice-receptionist/settings">
            <div className="avatar dark">
              {initials(auth.user.display_name)}
            </div>
            <div>
              <strong>{auth.user.display_name}</strong>
              <small>{auth.memberships[0]?.role || "Member"}</small>
            </div>
          </Link>
        </div>
      </aside>
      <div className="shell">
        <header>
          <span className="breadcrumb">
            Workspace <ChevronRight size={13} />{" "}
            <strong>{active?.name || "Page guide"}</strong>
          </span>
          <div className="headerRight">
            <span className="badge pale">Sample voice data</span>
            <Link className="button" href="/voice-receptionist/test">
              <Mic size={15} />
              Test agent
            </Link>
          </div>
        </header>
        <main id="main-content">
          <DemoBoundary>{children}</DemoBoundary>
        </main>
        <footer>
          Avishkar Voice{" "}
          <span>Demo workspace · No real calls or patient data</span>
          <Link href="/voice-receptionist/guide">Page guide</Link>
        </footer>
      </div>
    </>
  );
}
