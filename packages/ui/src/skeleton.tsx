import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

const shapes = {
  bar: "rounded-md",
  box: "rounded-[9px]",
  pill: "rounded-full",
  circle: "rounded-full",
};

/**
 * A placeholder for something that is still loading. Give it a size with width and height utilities (or `style` for a
 * size that is worked out at run time). It is hidden from assistive technology: wrap a group of them in
 * LoadingRegion, which says once that the page is loading.
 */
export function Skeleton({
  shape = "bar",
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  shape?: keyof typeof shapes;
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden
      className={cx(
        "animate-pulse bg-[#eceaf2] motion-reduce:animate-none",
        shapes[shape],
        className,
      )}
      {...props}
    />
  );
}

/** Wraps a loading layout: one polite announcement for screen readers, and a hook for tests. */
export function LoadingRegion({
  label,
  testId,
  children,
}: {
  label: string;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <div role="status" aria-busy="true" data-testid={testId}>
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}
