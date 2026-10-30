/**
 * What shows while the settings load. It has the same outline as the page (heading, status line, four panels, save
 * bar) and the same frame (sidebar and header). Change this file whenever the layout of settings-form.tsx or
 * shell.tsx changes.
 */
import { LoadingRegion, Panel, Skeleton } from "@clinic/ui";

export function SettingsSkeleton() {
  return (
    <div data-testid="settings-skeleton">
      <div className="mb-[25px]">
        <Skeleton className="mb-3 h-8 w-40" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <Skeleton className="mb-5 h-4 w-56" />
      {[
        { title: "w-56", rows: [28, 96] },
        { title: "w-48", rows: [40, 40, 40] },
        { title: "w-24", rows: [48, 48, 48] },
        { title: "w-32", rows: [32, 32, 32] },
      ].map((panel, i) => (
        <Panel key={i} className="mb-5">
          <Skeleton className={`mb-5 h-6 ${panel.title}`} />
          {panel.rows.map((h, j) => (
            <Skeleton key={j} className="mb-4 w-full last:mb-0" style={{ height: h }} />
          ))}
        </Panel>
      ))}
      <Skeleton className="mt-6 h-14 w-full" />
    </div>
  );
}

/** The whole page: sidebar, header and the settings outline, announced once. */
export function FrameSkeleton() {
  return (
    <LoadingRegion label="Loading lead response settings" testId="settings-loading">
      <div className="min-h-dvh bg-[#fafaf9] app:grid app:grid-cols-[260px_minmax(0,1fr)]">
        <div className="border-line bg-white p-5 max-app:border-b app:border-r">
          <Skeleton className="mb-6 h-9 w-36" />
          <Skeleton className="mb-4 h-16 w-full max-app:hidden" />
          <Skeleton className="mb-2 h-10 w-full max-app:hidden" />
        </div>
        <div className="min-w-0">
          <div className="border-line border-b bg-white px-6 py-3.5 max-app:px-4">
            <Skeleton className="h-5 w-40" />
          </div>
          <div className="mx-auto max-w-[820px] px-6 py-6 max-app:px-4">
            <SettingsSkeleton />
          </div>
        </div>
      </div>
    </LoadingRegion>
  );
}
