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
  BookOpen,
  Settings,
  ChevronRight,
} from "lucide-react";
import { Avatar, buttonStyles, StatusBadge } from "@clinic/ui";
import { Brand, DemoBoundary } from "./ui";
import { useAuth } from "@clinic/core/web/auth/provider";
import { initials } from "@clinic/core/web/auth/types";
import { useDemo } from "../lib/demo/provider";
export const navigation = [
  { path: "/voice-receptionist", name: "Overview", icon: LayoutDashboard },
  { path: "/voice-receptionist/agents", name: "Voice agents", icon: Bot },
  { path: "/voice-receptionist/numbers", name: "Phone numbers", icon: Phone },
  { path: "/voice-receptionist/calls", name: "Call history", icon: List },
  { path: "/voice-receptionist/test", name: "Test studio", icon: Mic },
  { path: "/voice-receptionist/tools", name: "Tools", icon: Code },
  { path: "/voice-receptionist/variables", name: "Variables", icon: Brackets },
  {
    path: "/voice-receptionist/knowledge",
    name: "Knowledge base",
    icon: BookOpen,
  },
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
      <a
        className="fixed -top-[100px] left-4 z-[200] bg-ink p-3 text-white focus:top-3"
        href="#main-content"
      >
        Skip to content
      </a>
      <aside
        data-testid="voice-sidebar"
        className="fixed inset-y-0 left-0 flex w-[245px] flex-col border-r border-line bg-white px-5 py-[30px] max-[1100px]:w-[205px] max-[1100px]:px-3 max-[1100px]:py-[25px] max-app:relative max-app:w-full max-app:p-4"
      >
        <Brand />
        <div className="my-7 flex gap-3 rounded-xl border border-line px-2.5 py-[17px] text-[14px] max-app:hidden">
          <Avatar>{state?.workspace.name[0] || "B"}</Avatar>
          <div>
            <strong
              className="block max-w-[140px] [overflow-wrap:anywhere]"
              data-testid="clinic-name"
            >
              {state?.workspace.name || "Voice workspace"}
            </strong>
            <small className="block text-[12px] text-muted">
              Voice workspace
            </small>
          </div>
        </div>
        <Link
          className="focus-ring -mt-2.5 mb-[18px] mx-3 block text-[12px] text-muted max-app:mt-3"
          href="/"
        >
          ← All clinic products
        </Link>
        <div className="mx-3 mb-2.5 text-[12px] tracking-[1.2px] text-[#96929f] max-app:hidden">
          WORKSPACE
        </div>
        <nav
          aria-label="Workspace navigation"
          className="max-app:mt-3 max-app:flex max-app:gap-1 max-app:overflow-auto"
        >
          {navigation.map(({ path, name, icon: Icon }) => {
            const current = active?.path === path;
            return (
              <Link
                key={path}
                href={path}
                aria-current={current ? "page" : undefined}
                className={`focus-ring my-[3px] flex items-center gap-[13px] rounded-[9px] p-3 text-[14px] max-app:gap-1.5 max-app:whitespace-nowrap max-app:p-[9px] max-app:text-[13px] ${current ? "bg-brand-soft font-semibold text-brand-ink" : "text-[#625d6b]"}`}
              >
                <Icon
                  size={19}
                  strokeWidth={1.7}
                  className="max-app:size-[15px]"
                />
                {name}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto max-app:hidden">
          <div className="rounded-[10px] bg-[#f7faf5] p-3.5 text-[12px]">
            <strong>Authenticated workspace</strong>
            <p className="my-1 text-[14px] text-muted">
              Agents, calls, tools and variables are live · other sections are
              demo
            </p>
          </div>
          <Link
            className="focus-ring flex gap-3 px-[5px] pt-5 text-[14px]"
            href="/voice-receptionist/settings"
          >
            <Avatar tone="dark">{initials(auth.user.display_name)}</Avatar>
            <div>
              <strong>{auth.user.display_name}</strong>
              <small className="block text-[12px] text-muted">
                {auth.memberships[0]?.role || "Member"}
              </small>
            </div>
          </Link>
        </div>
      </aside>
      <div className="ml-[245px] max-[1100px]:ml-[205px] max-app:ml-0">
        <header className="flex h-[79px] items-center justify-between border-b border-line bg-white px-[38px] text-[14px] text-muted max-[1100px]:px-6 max-app:h-[60px] max-app:px-[18px]">
          <span
            data-testid="voice-breadcrumb"
            className="flex items-center gap-2 max-app:text-[12px]"
          >
            Workspace <ChevronRight size={13} />{" "}
            <strong className="font-medium text-ink">
              {active?.name || "Page guide"}
            </strong>
          </span>
          <div className="flex items-center gap-4 max-app:gap-2">
            <span className="max-app:hidden">
              <StatusBadge>Live agents &amp; calls</StatusBadge>
            </span>
            <Link
              className={buttonStyles("outline", { size: "adaptive" })}
              href="/voice-receptionist/test"
            >
              <Mic size={15} />
              Test agent
            </Link>
          </div>
        </header>
        <main
          id="main-content"
          data-testid="voice-main"
          className="mx-auto min-h-[calc(100vh-138px)] min-w-0 max-w-[1440px] px-[38px] pb-[45px] pt-[34px] app:min-h-[calc(100vh/0.9-138px)] min-[1500px]:pt-[45px] max-[1100px]:px-6 max-[1100px]:pb-7 max-[1100px]:pt-7 max-app:px-[18px] max-app:pb-[25px] max-app:pt-[25px]"
        >
          <DemoBoundary>{children}</DemoBoundary>
        </main>
        <footer className="flex gap-6 border-t border-line px-[38px] py-[18px] text-[12px] text-muted max-app:flex-wrap max-app:gap-2 max-app:p-4">
          Avishkar Voice{" "}
          <span>
            Agents, calls, transcripts, tools, variables, the knowledge base and
            phone numbers are real and stored
          </span>
          <Link
            className="focus-ring ml-auto text-[#38691d]"
            href="/voice-receptionist/guide"
          >
            Page guide
          </Link>
        </footer>
      </div>
    </>
  );
}
