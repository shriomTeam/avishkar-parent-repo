/**
 * Small building blocks this feature needs that @clinic/ui does not have yet.
 * Candidates to promote into packages/ui: Skeleton, Notice, ProgressBar, RangeBar,
 * CollapsiblePanel, EmptyState, SectionTabs.
 */
import type { ReactNode } from "react";

export function Skeleton({
  width = "100%",
  height = 16,
}: {
  width?: number | string;
  height?: number | string;
}) {
  return <span aria-hidden className="dp-skeleton" style={{ width, height }} />;
}

const ICONS = {
  info: "M12 8v.01M12 11v5M12 3a9 9 0 100 18 9 9 0 000-18z",
  warn: "M12 9v4M12 17v.01M10.3 4.2L2.8 17.5A2 2 0 004.5 20.5h15a2 2 0 001.7-3L13.7 4.2a2 2 0 00-3.4 0z",
  error: "M12 8v5M12 16v.01M12 3a9 9 0 100 18 9 9 0 000-18z",
};
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
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
        <path d={ICONS[tone]} />
      </svg>
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
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  testId?: string;
}) {
  return (
    <div className="dp-empty" data-testid={testId}>
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}
