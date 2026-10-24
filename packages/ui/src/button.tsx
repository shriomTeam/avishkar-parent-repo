import type { ButtonHTMLAttributes } from "react";
import { cx } from "./cx";

export type ButtonVariant =
  "primary" | "secondary" | "brand" | "outline" | "danger" | "dangerOutline";
export type ButtonSize = "md" | "icon" | "pill" | "square" | "adaptive";

// primary and secondary are the platform's (teal); brand, outline and danger are the Avishkar brand look.
const base =
  "inline-flex items-center justify-center transition disabled:cursor-not-allowed disabled:opacity-50";
const brandShape = "focus-ring cursor-pointer border text-[14px] font-semibold";
// Sizes are separate so a caller never has to override padding or radius with another class.
const brandSizes: Record<ButtonSize, string> = {
  md: "gap-2 rounded-[9px] px-4 py-2.5",
  // Like md, but tighter on phones.
  adaptive: "gap-2 rounded-[9px] px-4 py-2.5 max-app:px-3 max-app:py-2",
  icon: "size-[42px] rounded-full p-0",
  pill: "h-[42px] min-w-[52px] rounded-full p-0",
  square: "size-[42px] rounded-[9px] p-0",
};
const brandColors = {
  brand: "border-brand bg-brand text-ink hover:bg-brand-hover",
  outline: "border-line bg-white text-ink hover:border-brand",
  dangerOutline:
    "border-line bg-white text-[#b72c43] hover:border-brand hover:text-ink",
  danger:
    "border-danger bg-danger text-white hover:bg-danger-hover hover:border-danger-hover",
};
const platform = {
  primary:
    "rounded-md bg-teal-700 px-3.5 py-2 text-sm font-medium text-white hover:bg-teal-800",
  secondary:
    "rounded-md border border-stone-300 bg-white px-3.5 py-2 text-sm font-medium text-stone-800 hover:bg-stone-50",
};

/** Class names for a button, so a link (`<Link>`) can look like one. */
export function buttonStyles(
  variant: ButtonVariant = "primary",
  { size = "md", className }: { size?: ButtonSize; className?: string } = {},
) {
  if (variant === "primary" || variant === "secondary")
    return cx(base, platform[variant], className);
  return cx(
    base,
    brandShape,
    brandSizes[size],
    brandColors[variant],
    className,
  );
}

export function Button({
  variant = "primary",
  size,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
}) {
  return (
    <button className={buttonStyles(variant, { size, className })} {...props} />
  );
}
