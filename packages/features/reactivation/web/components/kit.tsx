/**
 * This feature's own building blocks: the same visual language as the Voice receptionist, written here so the
 * feature does not depend on (or fight) the Tailwind classes in @clinic/ui.
 * Candidates to promote into packages/ui later: Button, Card, Stat, Skeleton, Notice, ProgressBar, RangeBar,
 * CollapsiblePanel, EmptyState, PageHead, Icon, the app shell.
 */
import Link from "next/link";
import type { AnchorHTMLAttributes, ButtonHTMLAttributes, ReactNode } from "react";

// --- icons: inline SVG, 24 px grid, 1.7 stroke, always decorative (the words next to them carry the meaning) ------

const ICON_PATHS = {
  upload: "M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3",
  download: "M12 4v12m0 0l-4.5-4.5M12 16l4.5-4.5M4 20h16",
  play: "M8 5.5v13l10.5-6.5L8 5.5z",
  mail: "M4 6h16a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V7a1 1 0 011-1zm-1 1l9 6.5L21 7",
  message: "M20 12a8 8 0 01-11.6 7.1L4 20l1-4.2A8 8 0 1120 12z",
  blocked: "M12 3a9 9 0 100 18 9 9 0 000-18zM5.6 5.6l12.8 12.8",
  info: "M12 8v.01M12 11v5M12 3a9 9 0 100 18 9 9 0 000-18z",
  warn: "M12 9v4M12 17v.01M10.3 4.2L2.8 17.5A2 2 0 004.5 20.5h15a2 2 0 001.7-3L13.7 4.2a2 2 0 00-3.4 0z",
  error: "M12 8v5M12 16v.01M12 3a9 9 0 100 18 9 9 0 000-18z",
  search: "M11 4a7 7 0 100 14 7 7 0 000-14zm5 12l4 4",
  file: "M14 3H7a1 1 0 00-1 1v16a1 1 0 001 1h10a1 1 0 001-1V7l-4-4zm0 0v4h4M9 13h6M9 17h6",
  users: "M16 19v-1.5a3.5 3.5 0 00-3.5-3.5h-5A3.5 3.5 0 004 17.5V19M10 4.5a3.25 3.25 0 100 6.5 3.25 3.25 0 000-6.5zM20 19v-1.5a3.5 3.5 0 00-2.6-3.4M15.5 4.7a3.25 3.25 0 010 6.1",
  clock: "M12 3a9 9 0 100 18 9 9 0 000-18zm0 4.5V12l3 2",
  overview: "M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z",
  chevron: "M9 6l6 6-6 6",
  settings: "M12 9a3 3 0 100 6 3 3 0 000-6zm7.4 3a7.4 7.4 0 00-.1-1.3l2-1.5-2-3.4-2.3.9a7.5 7.5 0 00-2.2-1.3L14.4 3h-4l-.4 2.4a7.5 7.5 0 00-2.2 1.3l-2.3-.9-2 3.4 2 1.5a7.4 7.4 0 000 2.6l-2 1.5 2 3.4 2.3-.9a7.5 7.5 0 002.2 1.3l.4 2.4h4l.4-2.4a7.5 7.5 0 002.2-1.3l2.3.9 2-3.4-2-1.5c.1-.4.1-.9.1-1.3z",
} as const;
export type IconName = keyof typeof ICON_PATHS;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="dp-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable="false"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

// --- the four primitives that used to come from @clinic/ui --------------------------------------------------------

/** Primary is the one main action on a page (lime fill, dark text). Secondary is everything else. */
export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" }) {
  return <button className={["dp-btn", className].filter(Boolean).join(" ")} data-variant={variant} {...props} />;
}

/** A link that looks like a Button, for actions that go to another page. */
export function ButtonLink({
  variant = "primary",
  className,
  href,
  ...props
}: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & { href: string; variant?: "primary" | "secondary" }) {
  return (
    <Link
      href={href}
      className={["dp-btn", className].filter(Boolean).join(" ")}
      data-variant={variant}
      {...props}
    />
  );
}

export function Card({
  title,
  action,
  children,
  className,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={["dp-card", className].filter(Boolean).join(" ")}>
      {(title || action) && (
        <header className="dp-card-head">
          {title && <h2 className="dp-card-title">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

/** A headline figure. `lead` gives the first tile the brand fill, as the Voice dashboard does. */
export function Stat({
  label,
  value,
  hint,
  lead = false,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  lead?: boolean;
}) {
  return (
    <div className="dp-stat" data-lead={lead || undefined}>
      <div className="dp-stat-label">{label}</div>
      <div className="dp-stat-value">{value}</div>
      {hint && <div className="dp-stat-hint">{hint}</div>}
    </div>
  );
}

/** A page title with its one-line description and, optionally, the page's actions on the right. */
export function PageHead({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="dp-head">
      <div>
        <h1 className="dp-title">{title}</h1>
        {description && <p className="dp-sub">{description}</p>}
      </div>
      {actions && <div className="dp-head-actions">{actions}</div>}
    </div>
  );
}

export function Skeleton({
  width = "100%",
  height = 16,
}: {
  width?: number | string;
  height?: number | string;
}) {
  return <span aria-hidden className="dp-skeleton" style={{ width, height }} />;
}

const LABELS = { info: "Note:", warn: "Heads up:", error: "Problem:" };

/** A message box. The label word and the icon carry the meaning, not just the colour. */
export function Notice({
  tone,
  title,
  children,
  action,
}: {
  tone: "info" | "warn" | "error";
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      className="dp-notice"
      data-tone={tone}
      role={tone === "error" ? "alert" : "status"}
    >
      <Icon name={tone} />
      <div>
        <strong>{title ?? LABELS[tone]}</strong> {children}
      </div>
      {action && <div className="dp-notice-actions">{action}</div>}
    </div>
  );
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className="dp-bar"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={pct}
    >
      <span style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Shows where a low-to-high range sits on a shared scale. The figures themselves are written next to it. */
export function RangeBar({
  low,
  high,
  max,
}: {
  low: number;
  high: number;
  max: number;
}) {
  const scale = max > 0 ? max : 1;
  const left = Math.min(100, (low / scale) * 100);
  const width = Math.max(0, Math.min(100 - left, ((high - low) / scale) * 100));
  return (
    <div className="dp-range" aria-hidden>
      <span style={{ left: `${left}%`, width: `${width}%` }} />
    </div>
  );
}

/** Native <details>: keyboard and screen-reader friendly without any script. */
export function CollapsiblePanel({
  title,
  children,
  testId,
}: {
  title: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <details className="dp-details" data-testid={testId}>
      <summary>{title}</summary>
      <div className="dp-details-body">{children}</div>
    </details>
  );
}

export function EmptyState({
  title,
  children,
  action,
  testId,
  icon,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  testId?: string;
  icon?: IconName;
}) {
  return (
    <div className="dp-empty" data-testid={testId}>
      {icon && (
        <span className="dp-empty-icon">
          <Icon name={icon} size={22} />
        </span>
      )}
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
