/**
 * Shared design system. Every feature's screens use these, so the product looks
 * like one system no matter which team built the page. Styling is Tailwind; the
 * app's globals.css includes this folder via @source.
 */
import type { ReactNode } from "react";
import { cx } from "./cx";

export { Button, buttonStyles, type ButtonVariant } from "./button";
export { Dialog, DialogActions } from "./dialog";
export { Dropdown, type DropdownOption } from "./dropdown";
export {
  CheckboxField,
  Input,
  NativeSelect,
  SwitchRow,
  TextAreaField,
  TextField,
  Textarea,
} from "./form";
export { Tabs } from "./tabs";
export { DataTable, Th, Td, Tr } from "./table";
export {
  Alert,
  Avatar,
  backLinkStyles,
  ChatMessage,
  CodeBlock,
  DetailList,
  EmptyState,
  FooterRow,
  footerRowStyles,
  H2,
  H3,
  Muted,
  Note,
  PageHeading,
  Panel,
  panelLinkStyles,
  PanelHead,
  Pill,
  SidebarLayout,
  StatCard,
  StatGrid,
  StatusBadge,
  SummaryList,
  TwoColumns,
  WideSplit,
} from "./layout";

export function Card({ title, action, children, className }: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-stone-200 bg-white p-5", className)}>
      {(title || action) && (
        <header className="mb-4 flex items-center justify-between gap-4">
          {title && <h2 className="text-sm font-semibold text-stone-900">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-stone-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-stone-900">{value}</div>
      {hint && <div className="mt-1 text-xs text-stone-500">{hint}</div>}
    </div>
  );
}

export function Badge({ tone = "neutral", children }: {
  tone?: "neutral" | "good" | "warn" | "locked";
  children: ReactNode;
}) {
  const tones = {
    neutral: "bg-stone-100 text-stone-700",
    good: "bg-teal-50 text-teal-800",
    warn: "bg-amber-50 text-amber-800",
    locked: "bg-stone-100 text-stone-500",
  };
  return <span className={cx("rounded px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function PageHeader({ title, description, action }: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-stone-900">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-stone-600">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function Table({ columns, rows }: { columns: string[]; rows: ReactNode[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-stone-200 text-xs uppercase tracking-wide text-stone-500">
            {columns.map((c) => (
              <th key={c} className="px-2 py-2 font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-stone-100 last:border-0">
              {r.map((cell, j) => (
                <td key={j} className="px-2 py-2 text-stone-800">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const formatCents = (cents: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(cents / 100);

export { Brand, Field, Select, FormError } from "./auth";
export { ProductCard, ProductGrid, navigationItemStyles } from "./workspace";
export { AccountMenu } from "./account-menu";
export { Pagination } from "./pagination";
