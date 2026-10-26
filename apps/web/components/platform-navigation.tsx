"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { AccountMenu, Avatar, navigationItemStyles } from "@clinic/ui";
import { ChevronRight, LayoutGrid, Upload, Sparkles } from "lucide-react";
import { featurePresentation } from "@/lib/feature-presentation";
import { WorkspaceSwitcher } from "@/components/auth/workspace-switcher";
import { useAuth } from "@/lib/auth/provider";
import { initials } from "@/lib/auth/types";

type Navigation = { feature: string; label: string; path: string }[];
export function PlatformNavigation({
  name,
  clinicType,
  status,
  userName,
  role,
  nav,
}: {
  name: string;
  clinicType: string;
  status: string;
  userName: string;
  role: string;
  nav: Navigation;
}) {
  const pathname = usePathname();
  const { auth, write } = useAuth();
  const items = [
    { path: "/", label: "Overview", icon: LayoutGrid },
    ...(["owner", "office_manager"].includes(role)
      ? [{ path: "/import", label: "Import data", icon: Upload }]
      : []),
    ...nav.map((item) => ({
      ...item,
      icon: featurePresentation({
        key: item.feature,
        name: item.label,
        description: "",
      }).icon,
    })),
  ];
  return (
    <aside className="flex shrink-0 flex-col border-b border-line bg-white md:sticky md:top-0 md:h-dvh md:w-[245px] md:border-r md:border-b-0">
      <div className="px-6 pt-7 pb-5">
        <Link
          href="/"
          aria-label="Always-On Clinic"
          className="focus-ring inline-flex items-center gap-2 text-[27px] font-bold tracking-[-1.3px]"
        >
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/brand/avishkar-logo.png" alt="" width={32} height={32} />
          avishkar
        </Link>
        <div className="mt-7 flex items-center gap-3 rounded-xl border border-line p-3">
          <Avatar>{initials(name)}</Avatar>
          <div className="min-w-0">
            <div
              data-testid="clinic-name"
              className="truncate text-[13px] font-semibold"
            >
              {name}
            </div>
            <div className="mt-1 text-[11px] text-muted capitalize">
              {clinicType} clinic
            </div>
          </div>
        </div>
      </div>
      <div className="px-5">
        <WorkspaceSwitcher />
      </div>
      <p className="px-7 pb-2 text-[10px] font-semibold tracking-[1.8px] text-muted">
        WORKSPACE
      </p>
      <nav
        aria-label="Workspace"
        className="flex gap-1 overflow-x-auto px-4 pb-4 md:flex-col md:overflow-y-auto"
      >
        {items.map(({ path, label, icon: Icon }) => {
          const active =
            path === "/"
              ? pathname === path
              : pathname === path || pathname.startsWith(`${path}/`);
          return (
            <Link
              key={path}
              href={path}
              aria-current={active ? "page" : undefined}
              className={navigationItemStyles(active)}
            >
              <Icon size={18} aria-hidden="true" />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto px-5 pt-4 pb-5">
        {status === "trial" && (
          <div className="mb-5 hidden rounded-xl bg-brand-soft p-4 md:block">
            <Sparkles
              size={18}
              className="mb-2 text-brand-ink"
              aria-hidden="true"
            />
            <p className="text-[13px] font-semibold text-brand-ink">
              Your clinic, always on.
            </p>
            <p className="mt-1 text-[12px] leading-5 text-brand-ink">
              You’re exploring your trial workspace.
            </p>
          </div>
        )}
        <AccountMenu
          name={userName}
          email={auth.user.email}
          role={role}
          initials={initials(userName)}
          onSignOut={async () => {
            await write("/api/v1/auth/logout");
            window.location.replace("/login");
          }}
        />
      </div>
    </aside>
  );
}

export function PlatformHeader({
  userName,
  nav,
}: {
  userName: string;
  nav: Navigation;
}) {
  const pathname = usePathname();
  const title =
    pathname === "/"
      ? "Overview"
      : pathname.startsWith("/settings")
        ? "Settings"
        : pathname.startsWith("/import")
          ? "Import data"
          : (nav.find(
              (item) =>
                pathname === item.path || pathname.startsWith(`${item.path}/`),
            )?.label ?? "Workspace");
  return (
    <header className="flex min-h-[76px] items-center justify-between gap-4 border-b border-line bg-white px-5 md:px-9">
      <div className="flex items-center gap-3 text-[13px]">
        <span className="text-muted">Workspace</span>
        <ChevronRight size={14} aria-hidden="true" />
        <span className="font-medium">{title}</span>
      </div>
      <div className="flex items-center gap-4">
        <Avatar>{initials(userName)}</Avatar>
      </div>
    </header>
  );
}
