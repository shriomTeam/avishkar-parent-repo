import type { ReactNode } from "react";

export function PlatformFrame({
  sidebar,
  children,
}: {
  sidebar: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen text-stone-900 antialiased">
      <div className="flex min-h-screen flex-col md:flex-row">
        {sidebar}
        <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
      </div>
    </div>
  );
}
