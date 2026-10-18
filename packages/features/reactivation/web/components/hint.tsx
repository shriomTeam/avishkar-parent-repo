"use client";
import { useId, type ReactNode } from "react";

/**
 * Text with a plain-language explanation that opens on hover and on keyboard focus, and is read out by screen
 * readers through aria-describedby. Escape closes it without moving focus away from the page's flow.
 */
export function Hint({
  children,
  text,
  testId,
}: {
  children: ReactNode;
  text: string;
  testId?: string;
}) {
  const id = useId();
  return (
    <span className="dp-hint-wrap" data-testid={testId}>
      <span
        className="dp-hint-trigger"
        tabIndex={0}
        aria-describedby={id}
        onKeyDown={(e) => {
          if (e.key === "Escape") e.currentTarget.blur();
        }}
      >
        {children}
      </span>
      <span role="tooltip" id={id} className="dp-tooltip">
        {text}
      </span>
    </span>
  );
}

/** "Not sized", with the reason. Never a bare dash. */
export function NotSized({ reason, label = "Not sized" }: { reason: string; label?: string }) {
  return (
    <Hint text={reason} testId="not-sized">
      <span className="dp-unsized">{label}</span>
    </Hint>
  );
}
