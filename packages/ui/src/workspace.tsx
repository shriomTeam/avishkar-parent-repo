import type { ComponentPropsWithoutRef, ReactNode } from "react";
import { cx } from "./cx";
import { Panel, StatusBadge } from "./layout";

/** Navigation styling shared by workspace shells; the host supplies routing. */
export function navigationItemStyles(active = false) {
  return cx(
    "focus-ring flex items-center gap-3 whitespace-nowrap rounded-[9px] px-3 py-3 text-[14px] font-medium transition",
    active
      ? "bg-brand-soft text-brand-ink"
      : "text-muted hover:bg-canvas hover:text-ink",
  );
}

export function ProductGrid({
  children,
  ...props
}: ComponentPropsWithoutRef<"div">) {
  return (
    <div {...props} className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
      {children}
    </div>
  );
}

/** Product presentation stays independent of feature implementations and routing. */
export function ProductCard({
  title,
  description,
  icon,
  active = false,
  action,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  active?: boolean;
  action?: ReactNode;
}) {
  return (
    <Panel as="article" className="flex h-full min-w-0 flex-col">
      <div className="mb-5 flex items-start justify-between gap-3">
        <span
          aria-hidden="true"
          className={cx(
            "grid size-11 shrink-0 place-items-center rounded-xl",
            active ? "bg-brand-soft text-brand-ink" : "bg-canvas text-muted",
          )}
        >
          {icon}
        </span>
        <StatusBadge tone={active ? "brand" : "muted"}>
          {active ? "Active" : "Not in plan"}
        </StatusBadge>
      </div>
      <h3 className="text-[16px] leading-6 font-semibold tracking-[-0.3px]">
        {title}
      </h3>
      <p className="mt-2 text-[14px] leading-6 text-muted">{description}</p>
      {action && (
        <div className="mt-auto pt-6 text-[14px] font-semibold text-brand-ink">
          {action}
        </div>
      )}
    </Panel>
  );
}
