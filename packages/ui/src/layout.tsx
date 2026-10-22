import type { ElementType, HTMLAttributes, ReactNode } from "react";
import { cx } from "./cx";

/** A white bordered surface. */
export function Panel({
  as: Tag = "section",
  className,
  ...props
}: HTMLAttributes<HTMLElement> & { as?: ElementType }) {
  return (
    <Tag
      className={cx(
        "rounded-[13px] border border-line bg-white p-[23px] max-app:p-[18px]",
        className,
      )}
      {...props}
    />
  );
}

/** A tinted message box. */
export function Note({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "rounded-[10px] bg-brand-soft p-[17px] text-[14px] text-[#365522] [&_p]:my-[7px] [&_p]:text-[14px] [&_p]:text-[#557445]",
        className,
      )}
      {...props}
    />
  );
}

export function PageHeading({
  title,
  description,
  actions,
  className,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cx(
        "mb-[25px] flex items-center justify-between gap-4 max-app:flex-wrap max-app:items-start",
        className,
      )}
    >
      <div>
        <h1 className="mb-[5px] text-[30px] font-[650] tracking-[-1px] max-app:text-[26px]">
          {title}
        </h1>
        {description && (
          <p className="my-[7px] text-[14px] text-muted">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex flex-wrap items-center gap-2.5 max-app:w-full">
          {actions}
        </div>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="px-5 py-10 text-center">
      <h2 className="my-[15px] text-[18px] font-bold tracking-[-0.4px]">
        {title}
      </h2>
      {description && (
        <p className="my-[7px] text-[14px] text-muted">{description}</p>
      )}
    </div>
  );
}

/** A headline number with a label and a line of context. `highlight` fills it with the brand colour. */
export function StatCard({
  label,
  value,
  hint,
  highlight = false,
}: {
  label: string;
  value: string;
  hint: string;
  highlight?: boolean;
}) {
  return (
    <div
      className={cx(
        "rounded-[13px] border p-[23px] max-app:p-[18px]",
        highlight ? "border-brand bg-brand text-ink" : "border-line bg-white",
      )}
    >
      <span
        className={cx(
          "text-[14px]",
          highlight ? "text-[#365522]" : "text-muted",
        )}
      >
        {label}
      </span>
      <div className="mb-[7px] mt-2.5 text-[clamp(22px,2.3vw,32px)] font-[650] tracking-[-1px] [overflow-wrap:anywhere] max-app:text-[24px]">
        {value}
      </div>
      <small
        className={cx(
          "block text-[12px]",
          highlight ? "text-[#365522]" : "text-muted",
        )}
      >
        {hint}
      </small>
    </div>
  );
}

/** A responsive row of StatCards: four across, two below 1100px. */
export function StatGrid({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "mb-[23px] grid grid-cols-4 gap-[18px] max-[1100px]:grid-cols-[repeat(2,minmax(0,1fr))] max-app:gap-2.5",
        className,
      )}
      {...props}
    />
  );
}

/** Label and value pairs, one per line. */
export function SummaryList({
  items,
  className,
}: {
  items: [string, ReactNode][];
  className?: string;
}) {
  return (
    <div
      className={cx(
        "grid content-start gap-[15px] text-[14px] max-app:text-[13px]",
        className,
      )}
    >
      {items.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-[15px]">
          <span className="text-muted">{label}</span>
          <strong className="min-w-0 text-right [overflow-wrap:anywhere]">
            {value}
          </strong>
        </div>
      ))}
    </div>
  );
}

export function CodeBlock({
  className,
  ...props
}: HTMLAttributes<HTMLPreElement>) {
  return (
    <pre
      className={cx(
        "whitespace-pre-wrap rounded-[9px] bg-[#f7f6fa] p-[15px] font-mono text-[13px] [overflow-wrap:anywhere]",
        className,
      )}
      {...props}
    />
  );
}

/** A round or rounded-square initial or icon on a tinted background. */
export function Avatar({
  children,
  tone = "brand",
  size = "md",
  className,
}: {
  children: ReactNode;
  tone?: "brand" | "dark";
  size?: "md" | "lg";
  className?: string;
}) {
  return (
    <div
      className={cx(
        "grid shrink-0 place-items-center rounded-[10px] font-bold",
        size === "lg" ? "size-[45px] text-[20px]" : "size-[35px] text-[14px]",
        tone === "dark" ? "bg-ink text-white" : "bg-brand-soft text-brand-ink",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function StatusBadge({
  tone = "brand",
  children,
}: {
  tone?: "brand" | "muted" | "danger" | "warn";
  children: ReactNode;
}) {
  const tones = {
    brand: "bg-brand-soft text-brand-ink",
    muted: "bg-neutral-soft text-neutral-ink",
    danger: "bg-danger-soft text-danger-ink",
    warn: "bg-warn-soft text-warn-ink",
  };
  return (
    <span
      className={cx(
        "inline-flex rounded-md px-2 py-1 text-[12px] font-semibold",
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

/** The heading of a panel, with an optional action (often a link) on the right. */
export function PanelHead({
  title,
  action,
  level = "h2",
}: {
  title: ReactNode;
  action?: ReactNode;
  level?: "h2" | "h3";
}) {
  const Heading = level;
  return (
    <div className="mb-5 flex items-center justify-between gap-3 max-app:flex-wrap">
      <Heading
        className={cx(
          "shrink-0",
          level === "h2"
            ? "text-[18px] font-bold tracking-[-0.4px]"
            : "mb-2.5 text-[16px] font-bold",
        )}
      >
        {title}
      </Heading>
      {action}
    </div>
  );
}

/** Two columns on desktop, one on narrow screens. */
export function TwoColumns({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "grid grid-cols-2 gap-[18px] max-app:grid-cols-1",
        className,
      )}
      {...props}
    />
  );
}

export function H2({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cx("text-[18px] font-bold tracking-[-0.4px]", className)}
      {...props}
    />
  );
}

/** A small heading. It leaves 10px below it unless `flush` is set. */
export function H3({
  className,
  flush = false,
  ...props
}: HTMLAttributes<HTMLHeadingElement> & { flush?: boolean }) {
  return (
    <h3
      className={cx(
        "text-[16px] font-bold",
        flush ? "mb-0" : "mb-2.5",
        className,
      )}
      {...props}
    />
  );
}

/** A paragraph in the quiet text colour. */
export function Muted({
  className,
  flush = false,
  ...props
}: HTMLAttributes<HTMLParagraphElement> & { flush?: boolean }) {
  return (
    <p
      className={cx(
        "text-[14px] text-muted",
        flush ? "my-0" : "my-[7px]",
        className,
      )}
      {...props}
    />
  );
}

/** An error or warning message. */
export function Alert({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      role="alert"
      className={cx(
        "my-3 rounded-lg bg-danger-soft px-3.5 py-2.5 text-danger-ink",
        className,
      )}
      {...props}
    />
  );
}

/** Class names for a "back to the list" link above a heading. */
export const backLinkStyles =
  "focus-ring mb-[18px] inline-flex items-center gap-[7px] text-[13px] text-[#38691d]";

/** A main column with a fixed-width side column; stacks on narrow screens. */
export function SidebarLayout({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "grid grid-cols-[minmax(0,1fr)_310px] gap-[22px] max-app:grid-cols-1 [&>*]:min-w-0",
        className,
      )}
      {...props}
    />
  );
}

/** A small label chip. */
export function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-[5px] bg-[#f3f8ef] px-[9px] py-[5px] text-[12px]">
      {children}
    </span>
  );
}

/** A wide main panel beside a narrower one; stacks below 1100px. */
export function WideSplit({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(
        "mb-[22px] grid grid-cols-[1.65fr_1fr] gap-[22px] max-[1100px]:grid-cols-1 [&>*]:min-w-0",
        className,
      )}
      {...props}
    />
  );
}

/** A line with a top border: a label on the left and a value on the right. Place it at the end of a panel. */
export const footerRowStyles =
  "mt-5 flex justify-between gap-3 border-t border-line pt-4 text-[14px] max-app:flex-wrap";

export function FooterRow({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx(footerRowStyles, className)} {...props} />;
}

/** One message in a conversation. */
export function ChatMessage({
  from,
  initial,
  name,
  children,
}: {
  from: "agent" | "caller";
  initial: string;
  name: ReactNode;
  children: ReactNode;
}) {
  const agent = from === "agent";
  return (
    <div className="my-[22px] flex gap-[15px] max-app:gap-2">
      <Avatar tone={agent ? "brand" : "dark"}>{initial}</Avatar>
      <div
        className={cx(
          "max-w-[80%] rounded-[0_12px_12px_12px] px-[17px] py-3.5 text-[14px] max-app:max-w-full",
          agent ? "bg-brand-soft" : "bg-[#f6f5f8]",
        )}
      >
        <strong className="mb-[5px] block text-[12px]">{name}</strong>
        {children}
      </div>
    </div>
  );
}

/** Names and values in a list, with a line between rows. */
export function DetailList({
  items,
  ...props
}: { items: [ReactNode, ReactNode][] } & HTMLAttributes<HTMLDListElement>) {
  return (
    <dl className="mt-2 grid gap-2" {...props}>
      {items.map(([label, value], index) => (
        <div
          key={index}
          className="flex justify-between gap-3.5 border-b border-line pb-1.5 text-[14px]"
        >
          <dt className="text-muted">{label}</dt>
          <dd className="m-0 text-right font-semibold [overflow-wrap:anywhere]">
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Class names for a small link in a panel heading ("View all"). */
export const panelLinkStyles = "focus-ring text-[14px] text-[#38691d]";
