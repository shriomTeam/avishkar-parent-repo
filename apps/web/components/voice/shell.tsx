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
} from "lucide-react";
import { DemoBoundary } from "./ui";
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
  return (
    <div className="voice-section">
      <a className="skip-link" href="#voice-content">
        Skip to voice content
      </a>
      <nav
        className="voice-navigation"
        aria-label="Voice receptionist navigation"
      >
        {navigation.map(({ path, name, icon: Icon }) => {
          const active =
            path === "/voice-receptionist"
              ? pathname === path
              : pathname.startsWith(path);
          return (
            <Link
              key={path}
              href={path}
              className={active ? "active" : ""}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={19} />
              {name}
            </Link>
          );
        })}
      </nav>
      <p className="voice-sample-notice">
        Sample voice data · simulated actions · no real calls or patient data
      </p>
      <div id="voice-content">
        <DemoBoundary>{children}</DemoBoundary>
      </div>
      <footer>
        Avishkar Voice <Link href="/voice-receptionist/guide">Page guide</Link>
      </footer>
    </div>
  );
}
