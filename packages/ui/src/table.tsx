import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cx } from "./cx";

/** A scrolling table container. Use with Th, Td and Tr. */
export function DataTable({
  className,
  children,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("max-w-full overflow-auto", className)} {...props}>
      <table className="w-full whitespace-nowrap border-collapse text-left text-[14px]">
        {children}
      </table>
    </div>
  );
}

export function Th({
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cx(
        "border-b border-line bg-[#fafafa] px-[13px] py-[15px] text-[12px] font-medium text-muted",
        className,
      )}
      {...props}
    />
  );
}

export function Td({
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cx(
        "border-b border-line px-[13px] py-[15px] group-last:border-0",
        className,
      )}
      {...props}
    />
  );
}

export function Tr({
  className,
  ...props
}: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr className={cx("group hover:bg-[#f6fff0]", className)} {...props} />
  );
}
