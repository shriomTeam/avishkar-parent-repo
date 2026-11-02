import type { ReactNode } from "react";

/** A message that is not an error: it says what happened. Announced politely, never takes focus. */
export function Notice({ title, children, testId }: { title: string; children?: ReactNode; testId: string }) {
  return (
    <div role="status" data-testid={testId} className="mb-4 rounded-[10px] border border-line bg-brand-soft p-4 text-[14px] text-brand-ink">
      <strong className="block text-[15px]">{title}</strong>
      {children && <div className="mt-1">{children}</div>}
    </div>
  );
}
