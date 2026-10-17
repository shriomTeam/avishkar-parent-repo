"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/reactivation", label: "Overview" },
  { href: "/reactivation/runs", label: "Runs" },
  { href: "/reactivation/settings", label: "Settings" },
];

export function SectionTabs() {
  const path = usePathname();
  const active = (href: string) =>
    href === "/reactivation"
      ? path === href || path.startsWith("/reactivation/types")
      : path === href || path.startsWith(`${href}/`);
  return (
    <nav className="dp-tabs" aria-label="Dormant patients sections">
      {TABS.map((tab) => (
        <Link
          key={tab.href}
          href={tab.href}
          className="dp-tab"
          aria-current={active(tab.href) ? "page" : undefined}
        >
          {tab.label}
        </Link>
      ))}
    </nav>
  );
}
