/** The sidebar items, which one is active for a path, and the breadcrumb. Kept free of React so it can be unit-tested. */
import type { IconName } from "./kit";

export const ROOT = "/reactivation";

export const NAV: { href: string; label: string; icon: IconName }[] = [
  { href: ROOT, label: "Overview", icon: "overview" },
  { href: `${ROOT}/runs`, label: "Runs", icon: "clock" },
  { href: `${ROOT}/settings`, label: "Settings", icon: "settings" },
];

/** The nav item a path belongs to. The patient-type pages are part of the Overview. */
export function activeHref(path: string): string | null {
  if (path === ROOT || path.startsWith(`${ROOT}/types`)) return ROOT;
  const hit = NAV.find((item) => item.href !== ROOT && (path === item.href || path.startsWith(`${item.href}/`)));
  return hit ? hit.href : null;
}

/** "Workspace" then the section, then "Patient group" on a type page. */
export function breadcrumb(path: string): string[] {
  const section = NAV.find((item) => item.href === activeHref(path));
  const trail = ["Workspace", section ? section.label : "Overview"];
  if (path.startsWith(`${ROOT}/types`)) trail.push("Patient group");
  return trail;
}
