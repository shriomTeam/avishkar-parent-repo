import type { ReactNode } from "react";

export function PlatformFrame({
  sidebar,
  header,
  children,
}: {
  sidebar: ReactNode;
  header?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen bg-canvas font-brand text-ink antialiased">
      <div className="flex min-h-screen flex-col md:flex-row">
        {sidebar}
        <div className="min-w-0 flex-1">
          {header}
          <main className="px-5 py-8 md:px-9 md:py-9">{children}</main>
        </div>
      </div>
    </div>
  );
}
