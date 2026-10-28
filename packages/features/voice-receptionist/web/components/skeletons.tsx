import type { ReactNode } from "react";
import {
  DataTable,
  FooterRow,
  LoadingRegion,
  Panel,
  SidebarLayout,
  Skeleton,
  StatGrid,
  Td,
  Th,
  Tr,
  TwoColumns,
  WideSplit,
} from "@clinic/ui";

/*
 * What each voice screen looks like while its data loads. They are built from the same layout pieces as the real
 * screens (Panel, StatGrid, WideSplit, DataTable, SidebarLayout...), so the page does not jump when the content
 * arrives. When a screen's layout changes, change its skeleton here too.
 *
 * Widths are plain pixel numbers because a skeleton has no content to size itself from.
 */

/** The same wrapper as PageHeading: a title line, a description line, and optional buttons. */
function HeadingSkeleton({ buttons = [] }: { buttons?: number[] }) {
  return (
    <div className="mb-[25px] flex items-center justify-between gap-4 max-app:flex-wrap max-app:items-start">
      <div>
        <Skeleton className="mb-[9px] h-[30px] w-[280px] max-w-full" />
        <Skeleton className="my-[7px] h-[14px] w-[360px] max-w-full" />
      </div>
      {buttons.length > 0 && (
        <div className="flex flex-wrap items-center gap-2.5 max-app:w-full">
          {buttons.map((width, i) => (
            <Skeleton
              key={i}
              shape="box"
              className="h-[42px]"
              style={{ width }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** The heading line of a panel, with an optional action on the right. */
function PanelHeadSkeleton({
  title = 150,
  action,
}: {
  title?: number;
  action?: number;
}) {
  return (
    <div className="mb-5 flex items-center justify-between gap-3">
      <Skeleton className="h-[20px]" style={{ width: title }} />
      {action && (
        <Skeleton shape="pill" className="h-4" style={{ width: action }} />
      )}
    </div>
  );
}

function StatCardSkeleton({ highlight = false }: { highlight?: boolean }) {
  return (
    <div
      className={`rounded-[13px] border p-[23px] max-app:p-[18px] ${highlight ? "border-brand bg-brand-soft" : "border-line bg-white"}`}
    >
      <Skeleton className="h-[14px] w-[110px]" />
      <Skeleton className="mb-[7px] mt-2.5 h-[32px] w-[90px]" />
      <Skeleton className="h-3 w-[150px] max-w-full" />
    </div>
  );
}

function StatsSkeleton() {
  return (
    <StatGrid>
      <StatCardSkeleton highlight />
      <StatCardSkeleton />
      <StatCardSkeleton />
      <StatCardSkeleton />
    </StatGrid>
  );
}

/** A table with a header row and `rows` body rows; `columns` are the column widths. */
function TableSkeleton({
  columns,
  rows = 4,
}: {
  columns: number[];
  rows?: number;
}) {
  return (
    <DataTable>
      <thead>
        <tr>
          {columns.map((width, i) => (
            <Th key={i}>
              <Skeleton className="h-3" style={{ width: width * 0.7 }} />
            </Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, row) => (
          <Tr key={row}>
            {columns.map((width, i) => (
              <Td key={i}>
                <Skeleton className="h-[14px]" style={{ width }} />
              </Td>
            ))}
          </Tr>
        ))}
      </tbody>
    </DataTable>
  );
}

/** A few lines of text, for a list that is still arriving inside a screen that has already loaded. */
export function LinesSkeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div role="status" aria-busy="true" className="my-3 grid gap-3">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton
          key={i}
          className="h-[14px]"
          style={{ width: `${90 - i * 18}%` }}
        />
      ))}
    </div>
  );
}

/** A table that is still arriving inside a screen that has already loaded. */
export function TableLoading({
  columns,
  rows = 3,
}: {
  columns: number[];
  rows?: number;
}) {
  return (
    <div role="status" aria-busy="true">
      <span className="sr-only">Loading…</span>
      <TableSkeleton columns={columns} rows={rows} />
    </div>
  );
}

function AvatarRowSkeleton() {
  return (
    <div className="my-[18px] flex items-center gap-3">
      <Skeleton shape="circle" className="size-[38px]" />
      <div className="flex-1">
        <Skeleton className="mb-2 h-[14px] w-[140px]" />
        <Skeleton className="h-3 w-[200px] max-w-full" />
      </div>
      <Skeleton shape="pill" className="h-[22px] w-[64px]" />
    </div>
  );
}

function FieldSkeleton({
  label = 120,
  height = 44,
}: {
  label?: number;
  height?: number;
}) {
  return (
    <div className="mb-[21px]">
      <Skeleton className="mb-2.5 h-[14px]" style={{ width: label }} />
      <Skeleton shape="box" style={{ height }} />
    </div>
  );
}

function TabsSkeleton({ tabs = 4 }: { tabs?: number }) {
  return (
    <div className="mb-5 flex gap-6 border-b border-line pb-3">
      {Array.from({ length: tabs }, (_, i) => (
        <Skeleton key={i} className="h-[16px] w-[96px]" />
      ))}
    </div>
  );
}

function SummaryRowsSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="flex justify-between gap-3 border-b border-line py-3.5 last:border-0"
        >
          <Skeleton className="h-[14px] w-[110px]" />
          <Skeleton className="h-[14px] w-[90px]" />
        </div>
      ))}
    </div>
  );
}

/** A tinted note: a title and two lines by default, or a single line (`banner`) for the notes at the top of a screen. */
function NoteSkeleton({ banner = false }: { banner?: boolean }) {
  return (
    <div
      className={`rounded-[10px] bg-brand-soft p-[17px] ${banner ? "mb-[18px]" : "mt-5"}`}
    >
      {banner ? (
        <Skeleton className="h-[14px] w-[70%]" />
      ) : (
        <>
          <Skeleton className="mb-3 h-[14px] w-[160px]" />
          <Skeleton className="mb-2 h-3 w-full" />
          <Skeleton className="h-3 w-[75%]" />
        </>
      )}
    </div>
  );
}

function Screen({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: ReactNode;
}) {
  return (
    <LoadingRegion label={label} testId={`loading-${id}`}>
      {children}
    </LoadingRegion>
  );
}

// ---- one skeleton per screen ---------------------------------------------------------------------------------------

export function OverviewSkeleton() {
  return (
    <Screen label="Loading your overview" id="overview">
      <HeadingSkeleton buttons={[134, 150]} />
      <StatsSkeleton />
      <WideSplit>
        <Panel>
          <PanelHeadSkeleton title={120} action={150} />
          <div className="flex h-[195px] items-end gap-[17px] px-3 pb-6 max-app:gap-2.5 min-[1500px]:h-[240px]">
            {[38, 64, 30, 82, 52, 70, 44].map((height, i) => (
              <Skeleton
                key={i}
                className="flex-1 rounded-b-none rounded-t-[5px]"
                style={{ height: `${height}%` }}
              />
            ))}
          </div>
          <Skeleton className="mt-3 h-3 w-[200px]" />
        </Panel>
        <Panel>
          <PanelHeadSkeleton title={110} action={56} />
          <AvatarRowSkeleton />
          <AvatarRowSkeleton />
          <FooterRow>
            <Skeleton className="h-[14px] w-[100px]" />
            <Skeleton className="h-[14px] w-[24px]" />
          </FooterRow>
        </Panel>
      </WideSplit>
      <Panel>
        <PanelHeadSkeleton title={110} action={110} />
        <TableSkeleton columns={[110, 120, 100, 56, 70, 40, 90]} rows={4} />
      </Panel>
    </Screen>
  );
}

export function AgentsSkeleton() {
  return (
    <Screen label="Loading your voice agents" id="agents">
      <HeadingSkeleton buttons={[140]} />
      <div className="grid grid-cols-3 gap-[22px] max-[1100px]:grid-cols-2 max-app:grid-cols-1 [&>*]:min-w-0">
        {[0, 1, 2].map((i) => (
          <article
            key={i}
            className="rounded-[13px] border border-line bg-white p-6 max-app:p-[18px]"
          >
            <div className="mb-5 flex items-center justify-between gap-3">
              <Skeleton shape="circle" className="size-[52px]" />
              <Skeleton shape="pill" className="h-[22px] w-[64px]" />
            </div>
            <Skeleton className="mb-3 mt-[22px] h-[20px] w-[160px]" />
            <Skeleton className="mb-2 h-[14px] w-full" />
            <Skeleton className="h-[14px] w-[70%]" />
            <div className="mt-[18px] flex gap-2.5">
              <Skeleton shape="pill" className="h-[24px] w-[64px]" />
              <Skeleton shape="pill" className="h-[24px] w-[64px]" />
            </div>
            <div className="my-[22px] flex gap-[25px] border-t border-line pt-[18px]">
              <div>
                <Skeleton className="mb-2 h-[16px] w-[28px]" />
                <Skeleton className="h-3 w-[70px]" />
              </div>
              <div>
                <Skeleton className="mb-2 h-[16px] w-[28px]" />
                <Skeleton className="h-3 w-[90px]" />
              </div>
            </div>
            <Skeleton shape="box" className="h-[42px] w-full" />
          </article>
        ))}
      </div>
    </Screen>
  );
}

export function AgentEditorSkeleton() {
  return (
    <Screen label="Loading the agent" id="agent-editor">
      <HeadingSkeleton buttons={[110, 90, 130]} />
      <TabsSkeleton />
      <SidebarLayout>
        <Panel>
          <TwoColumns>
            <FieldSkeleton label={100} />
            <FieldSkeleton label={80} />
          </TwoColumns>
          <FieldSkeleton label={90} />
          <FieldSkeleton label={110} height={170} />
          <FieldSkeleton label={110} height={90} />
          <div className="w-1/2 max-app:w-full">
            <FieldSkeleton label={50} />
          </div>
        </Panel>
        <div>
          <Panel>
            <PanelHeadSkeleton title={140} action={64} />
            <SummaryRowsSkeleton rows={5} />
          </Panel>
          <NoteSkeleton />
        </div>
      </SidebarLayout>
    </Screen>
  );
}

export function CallsSkeleton() {
  return (
    <Screen label="Loading call history" id="calls">
      <HeadingSkeleton buttons={[134]} />
      <Panel>
        <div className="mb-5 flex items-center gap-3 max-app:flex-wrap">
          <Skeleton
            shape="box"
            className="h-[44px] flex-1 max-app:basis-full"
          />
          <Skeleton shape="box" className="h-[44px] w-[170px]" />
          <Skeleton shape="box" className="h-[44px] w-[170px]" />
        </div>
        <TableSkeleton columns={[110, 120, 100, 56, 70, 40, 90]} rows={6} />
      </Panel>
    </Screen>
  );
}

export function CallDetailSkeleton() {
  return (
    <Screen label="Loading the call" id="call-detail">
      <HeadingSkeleton />
      <StatsSkeleton />
      <SidebarLayout>
        <Panel>
          <Skeleton shape="box" className="mb-5 h-[54px] w-full" />
          <TabsSkeleton tabs={4} />
          {[0, 1, 2].map((i) => (
            <div key={i} className="my-[22px] flex gap-[15px]">
              <Skeleton shape="circle" className="size-[38px] shrink-0" />
              <div className="w-[70%] max-w-full rounded-[0_12px_12px_12px] bg-[#f6f5f8] px-[17px] py-3.5">
                <Skeleton className="mb-2 h-[14px] w-full" />
                <Skeleton className="h-[14px] w-[60%]" />
              </div>
            </div>
          ))}
        </Panel>
        <div>
          <Panel>
            <PanelHeadSkeleton title={120} />
            <SummaryRowsSkeleton rows={5} />
          </Panel>
          <Panel className="mt-5">
            <PanelHeadSkeleton title={60} />
            <Skeleton className="h-[14px] w-[80%]" />
          </Panel>
        </div>
      </SidebarLayout>
    </Screen>
  );
}

export function TestStudioSkeleton() {
  return (
    <Screen label="Loading test studio" id="test-studio">
      <HeadingSkeleton buttons={[120]} />
      <WideSplit>
        <Panel>
          <PanelHeadSkeleton title={130} action={64} />
          <Skeleton shape="box" className="h-[44px] w-full" />
          <div className="grid place-items-center py-[42px]">
            <Skeleton shape="circle" className="size-[110px]" />
            <Skeleton className="mt-5 h-[20px] w-[170px]" />
            <Skeleton className="mt-3 h-[14px] w-[240px] max-w-full" />
            <Skeleton shape="box" className="mt-6 h-[44px] w-[180px]" />
          </div>
          <NoteSkeleton />
        </Panel>
        <Panel>
          <PanelHeadSkeleton title={110} />
          {[0, 1].map((i) => (
            <div key={i} className="my-[22px] flex gap-[15px]">
              <Skeleton shape="circle" className="size-[38px] shrink-0" />
              <div className="w-[70%] max-w-full rounded-[0_12px_12px_12px] bg-[#f6f5f8] px-[17px] py-3.5">
                <Skeleton className="mb-2 h-[14px] w-full" />
                <Skeleton className="h-[14px] w-[50%]" />
              </div>
            </div>
          ))}
        </Panel>
      </WideSplit>
    </Screen>
  );
}

export function ToolsSkeleton() {
  return (
    <Screen label="Loading your tools" id="tools">
      <HeadingSkeleton buttons={[120]} />
      <div className="grid gap-5">
        {[0].map((i) => (
          <Panel key={i}>
            <div className="mb-4 flex items-center gap-3">
              <Skeleton shape="box" className="size-[42px]" />
              <Skeleton className="h-[20px] w-[150px]" />
              <Skeleton shape="pill" className="ml-auto h-[22px] w-[64px]" />
            </div>
            <Skeleton className="mb-2 h-[14px] w-full" />
            <Skeleton className="mb-5 h-[14px] w-[65%]" />
            <SummaryRowsSkeleton rows={3} />
            <div className="mt-5 flex justify-end gap-2.5">
              <Skeleton shape="box" className="h-[42px] w-[120px]" />
              <Skeleton shape="box" className="h-[42px] w-[90px]" />
            </div>
          </Panel>
        ))}
      </div>
      <WideSplit className="mt-5">
        <Panel>
          <PanelHeadSkeleton title={150} />
          <TableSkeleton columns={[110, 120, 70, 60]} rows={3} />
        </Panel>
        <Panel>
          <PanelHeadSkeleton title={170} />
          <Skeleton className="mb-3 h-[14px] w-full" />
          <Skeleton className="mb-3 h-[14px] w-[90%]" />
          <Skeleton className="mb-3 h-[14px] w-[95%]" />
          <Skeleton className="h-[14px] w-[70%]" />
        </Panel>
      </WideSplit>
    </Screen>
  );
}

export function VariablesSkeleton() {
  return (
    <Screen label="Loading your variables" id="variables">
      <HeadingSkeleton buttons={[140]} />
      <Panel>
        <PanelHeadSkeleton title={130} />
        <TableSkeleton columns={[110, 240, 120, 130]} rows={3} />
      </Panel>
      <Panel className="mt-5">
        <PanelHeadSkeleton title={170} />
        <Skeleton className="mb-4 h-[14px] w-[60%]" />
        <TableSkeleton columns={[110, 240, 120]} rows={5} />
      </Panel>
      <NoteSkeleton />
    </Screen>
  );
}

export function KnowledgeSkeleton() {
  return (
    <Screen label="Loading your knowledge base" id="knowledge">
      <HeadingSkeleton buttons={[130]} />
      <Panel>
        <PanelHeadSkeleton title={140} />
        <TableSkeleton columns={[220, 56, 100, 80, 130]} rows={3} />
      </Panel>
      <NoteSkeleton />
    </Screen>
  );
}

export function NumbersSkeleton() {
  return (
    <Screen label="Loading your phone numbers" id="numbers">
      <HeadingSkeleton buttons={[140]} />
      <NoteSkeleton banner />
      <Panel>
        <TableSkeleton columns={[150, 60, 130, 90, 90]} rows={2} />
        <Skeleton className="mt-4 h-3 w-[360px] max-w-full" />
      </Panel>
      <WideSplit className="mt-5">
        <Panel>
          <PanelHeadSkeleton title={190} />
          <Skeleton className="mb-3 h-[14px] w-[260px] max-w-full" />
          <FooterRow>
            <Skeleton className="h-[14px] w-[110px]" />
            <Skeleton className="h-[14px] w-[120px]" />
          </FooterRow>
          <FooterRow>
            <Skeleton className="h-[14px] w-[150px]" />
            <Skeleton className="h-[14px] w-[170px]" />
          </FooterRow>
        </Panel>
        <Panel>
          <PanelHeadSkeleton title={140} />
          <Skeleton className="mb-2 h-[14px] w-full" />
          <Skeleton className="mb-5 h-[14px] w-[70%]" />
          <Skeleton shape="box" className="h-[42px] w-[150px]" />
        </Panel>
      </WideSplit>
    </Screen>
  );
}

/** For any voice route that has no screen of its own while it loads. */
export function PageSkeleton() {
  return (
    <Screen label="Loading your workspace" id="page">
      <HeadingSkeleton buttons={[130]} />
      <Panel>
        <TableSkeleton columns={[180, 140, 100, 90]} rows={5} />
      </Panel>
    </Screen>
  );
}
