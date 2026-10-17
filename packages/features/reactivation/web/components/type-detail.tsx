"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button, Card, Stat } from "@clinic/ui";
import { useAuth } from "@clinic/core/web/auth/provider";
import type { paths } from "@clinic/api-client";

import type { LatestRun, TypeEntry } from "../lib/api-types";
import { browserClient } from "../lib/client";
import { formatCount, formatDateTime, formatMoney, formatRange, rateBasisText, relativeTime } from "../lib/format";
import { NOT_SIZED, unavailableAction, unavailableReason } from "../lib/messages";
import {
  DEFAULT_STATE,
  PAGE_SIZE,
  apiParams,
  applyList,
  clampPage,
  clearFilters,
  hasStatusFilter,
  isFiltered,
  pageCount,
  parseUrlState,
  rowFromFile,
  rowFromSaved,
  serializeUrlState,
  typeHref,
  type ListState,
  type PatientRow,
} from "../lib/patient-list";
import { CsvBanner } from "./csv-results";
import { useCsvResult } from "./csv-provider";
import { NotSized } from "./hint";
import { EmptyState, Notice, Skeleton } from "./kit";
import { PatientControls } from "./patient-controls";
import { PatientTable } from "./patient-table";

type PatientsQuery = NonNullable<
  paths["/features/reactivation/runs/{run_id}/patients"]["get"]["parameters"]["query"]
>;
const CAN_LIST = new Set(["owner", "office_manager"]);
const SEARCH_PAUSE_MS = 300;

type Mode = "saved" | "file";

// --- the page ----------------------------------------------------------------------------------------------------------

export function TypeDetail({ typeKey }: { typeKey: string }) {
  const params = useSearchParams();
  const router = useRouter();
  const { result } = useCsvResult();
  const fromFile = params.get("source") === "file";

  // File results live only in memory. After a refresh they are gone, so go back to the Overview and say so.
  useEffect(() => {
    if (fromFile && !result) router.replace("/reactivation?notice=file-cleared");
  }, [fromFile, result, router]);

  if (fromFile) {
    if (!result)
      return (
        <p className="dp-sub" role="status" data-testid="file-gone">
          Your file results are no longer in this tab. Taking you back to the overview…
        </p>
      );
    return <FileType typeKey={typeKey} />;
  }
  return <SavedType typeKey={typeKey} />;
}

// --- file mode -----------------------------------------------------------------------------------------------------------

function FileType({ typeKey }: { typeKey: string }) {
  const { result } = useCsvResult();
  const data = result!.data;
  const entry = data.types.find((t) => t.type_key === typeKey) ?? null;
  const rows = useMemo(() => data.patients.map(rowFromFile), [data]);
  return (
    <TypeFrame
      typeKey={typeKey}
      mode="file"
      entry={entry}
      backHref="/reactivation"
      banner={<CsvBanner fileName={result!.fileName} />}
    >
      <PatientList typeKey={typeKey} entry={entry} source={{ kind: "file", rows }} />
    </TypeFrame>
  );
}

// --- saved mode ----------------------------------------------------------------------------------------------------------

type Prerequisites =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "none"; active: { status: string } | null }
  | { kind: "ready"; run: LatestRun; types: TypeEntry[]; active: { status: string } | null };

function SavedType({ typeKey }: { typeKey: string }) {
  const { auth } = useAuth();
  const { result } = useCsvResult();
  const tenantId = auth.workspace?.id;
  const timeZone = auth.workspace?.timezone ?? "America/New_York";
  const role = auth.memberships.find((m) => m.workspace_id === tenantId)?.role;
  const client = useMemo(() => browserClient(auth.csrf_token, tenantId), [auth.csrf_token, tenantId]);
  const [pre, setPre] = useState<Prerequisites>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => setNow(new Date()), []);
  useEffect(() => {
    let cancelled = false;
    setPre({ kind: "loading" });
    (async () => {
      try {
        const [runs, latest] = await Promise.all([
          client.GET("/features/reactivation/runs"),
          client.GET("/features/reactivation/runs/latest"),
        ]);
        if (cancelled) return;
        if (!runs.data || (!latest.data && latest.response.status !== 404)) return setPre({ kind: "error" });
        const active = runs.data.find((r) => r.status === "queued" || r.status === "running") ?? null;
        if (!latest.data) return setPre({ kind: "none", active });
        const types = await client.GET("/features/reactivation/runs/{run_id}/types", {
          params: { path: { run_id: latest.data.id } },
        });
        if (cancelled) return;
        if (!types.data) return setPre({ kind: "error" });
        setPre({ kind: "ready", run: latest.data, types: types.data, active });
      } catch {
        if (!cancelled) setPre({ kind: "error" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, attempt]);

  const backHref = result ? "/reactivation?view=saved" : "/reactivation";
  const banner = result ? (
    <Notice
      tone="info"
      title="File results are also open in this tab."
      action={
        <Link href={typeHref(typeKey, true)} className="dp-link-button">
          View file results
        </Link>
      }
    >
      What you see below is your saved data.
    </Notice>
  ) : null;

  if (pre.kind === "loading") return <TypeSkeleton />;
  if (pre.kind === "error")
    return (
      <Shell backHref={backHref}>
        <Card>
          <EmptyState
            title="We couldn't load this page"
            action={<Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button>}
          >
            Something went wrong while loading your results. Your data is safe.
          </EmptyState>
        </Card>
      </Shell>
    );
  if (pre.kind === "none")
    return (
      <Shell backHref={backHref}>
        {banner}
        <Card>
          <EmptyState title={pre.active ? "Your first analysis is still running" : "There are no results yet"}>
            {pre.active
              ? "This page will have patients once the analysis finishes. You can leave and come back."
              : "Run your first analysis from the overview, and the patients will be listed here."}
          </EmptyState>
        </Card>
      </Shell>
    );

  const entry = pre.types.find((t) => t.type_key === typeKey) ?? null;
  const canList = !!role && CAN_LIST.has(role);
  return (
    <TypeFrame typeKey={typeKey} mode="saved" entry={entry} backHref={backHref} banner={banner}>
      {pre.active && (
        <Notice tone="info" title="A new analysis is running.">
          This list shows the results from{" "}
          {pre.run.finished_at
            ? now
              ? relativeTime(pre.run.finished_at, now)
              : formatDateTime(pre.run.finished_at, timeZone)
            : "the last analysis"}
          .
        </Notice>
      )}
      {!canList ? (
        <Card>
          <EmptyState title="This page is for clinic owners and office managers" testId="no-role">
            Patient lists are only shown to the clinic owner and office managers. You can still see the totals above.
          </EmptyState>
        </Card>
      ) : (
        <PatientList
          typeKey={typeKey}
          entry={entry}
          source={{ kind: "saved", runId: pre.run.id, timeZone, client }}
        />
      )}
    </TypeFrame>
  );
}

// --- shared frame: header, summary, unavailable view -----------------------------------------------------------------

function Shell({ backHref, children }: { backHref: string; children: ReactNode }) {
  return (
    <div className="dp-stack">
      <Link href={backHref} className="dp-back">
        ← Back to overview
      </Link>
      {children}
    </div>
  );
}

function TypeFrame({
  typeKey,
  mode,
  entry,
  backHref,
  banner,
  children,
}: {
  typeKey: string;
  mode: Mode;
  entry: TypeEntry | null;
  backHref: string;
  banner: ReactNode;
  children: ReactNode;
}) {
  if (!entry)
    return (
      <Shell backHref={backHref}>
        {banner}
        <Card>
          <EmptyState title="That group doesn't exist">
            There&apos;s no patient group called this. Go back to the overview and pick one from the table.
          </EmptyState>
        </Card>
      </Shell>
    );
  const body = (
    <>
      <Summary entry={entry} mode={mode} />
      {entry.available ? children : <Unavailable entry={entry} mode={mode} typeKey={typeKey} />}
    </>
  );
  return (
    <Shell backHref={backHref}>
      <div className="dp-head">
        <div>
          <h1 className="dp-title" data-testid="type-title">
            {entry.label}
            {mode === "file" && <span className="dp-from-file">from file</span>}
          </h1>
          <p className="dp-sub">{entry.description}</p>
        </div>
      </div>
      {banner}
      {mode === "file" ? (
        <div className="dp-file-frame" data-testid="csv-frame">
          {body}
        </div>
      ) : (
        <div className="dp-stack">{body}</div>
      )}
    </Shell>
  );
}

function Summary({ entry: t, mode }: { entry: TypeEntry; mode: Mode }) {
  const unavailable = mode === "file" ? "Not available from this file" : "Not available for this clinic";
  let worth: ReactNode;
  let worthHint: string | undefined;
  if (!t.available) worth = <span className="dp-unavailable">{unavailable}</span>;
  else if (t.type_key === "unclassified") worth = <NotSized reason={NOT_SIZED.unclassified} />;
  else if (t.revenue_low_cents === null || t.revenue_high_cents === null)
    worth = <NotSized reason={NOT_SIZED.groupNoBasis} />;
  else if (t.kind === "retention") {
    worth = formatMoney(t.revenue_low_cents);
    worthHint = "Already paid, locked in. Not new revenue.";
  } else {
    worth = formatRange(t.revenue_low_cents, t.revenue_high_cents);
    worthHint =
      t.rate_low !== null && t.rate_high !== null ? rateBasisText(t.rate_source, t.rate_low, t.rate_high) : undefined;
  }
  const top = !t.available ? (
    <span className="dp-unavailable">Not available</span>
  ) : t.type_key === "unclassified" ? (
    <NotSized reason={NOT_SIZED.noService} />
  ) : (
    (t.top_service_name ?? "Not recorded")
  );
  return (
    <div className="dp-tiles" data-testid="type-summary">
      <div data-testid="summary-patients">
        <Stat label="Patients" value={t.patient_count === null ? "Not available" : formatCount(t.patient_count)} />
      </div>
      <div data-testid="summary-worth">
        <Stat label="Could be worth" value={worth} hint={worthHint} />
      </div>
      <div data-testid="summary-top-service">
        <Stat label="Top service" value={top} />
      </div>
    </div>
  );
}

function Unavailable({ entry, mode, typeKey }: { entry: TypeEntry; mode: Mode; typeKey: string }) {
  return (
    <Card>
      <div className="dp-unavailable-card" data-testid="type-unavailable">
        <h2>{mode === "file" ? "Not available from this file" : "Not available for this clinic"}</h2>
        <p>{unavailableReason(typeKey, mode)}</p>
        <p className="dp-what-to-do">
          <strong>What you can do:</strong> {unavailableAction(typeKey, mode)}
        </p>
        {mode === "saved" ? (
          <Link href="/import" className="dp-link-button">
            Go to Import data
          </Link>
        ) : (
          <Link href="/reactivation" className="dp-link-button">
            Back to the file overview
          </Link>
        )}
        <span className="dp-visually-hidden">{entry.label}</span>
      </div>
    </Card>
  );
}

// --- the list --------------------------------------------------------------------------------------------------------------

type ListSource =
  | { kind: "file"; rows: PatientRow[] }
  | { kind: "saved"; runId: string; timeZone: string; client: ReturnType<typeof browserClient> };

type Loaded =
  | { kind: "loading"; items: PatientRow[]; total: number; first: boolean }
  | { kind: "ready"; items: PatientRow[]; total: number }
  | { kind: "error"; items: PatientRow[]; total: number };

function PatientList({ typeKey, entry, source }: { typeKey: string; entry: TypeEntry | null; source: ListSource }) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [fileState, setFileState] = useState<ListState>(DEFAULT_STATE);
  const [search, setSearch] = useState("");
  const [typed, setTyped] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const isFile = source.kind === "file";

  // The search text is kept out of the URL (names must not reach the address bar or history).
  // Saved mode: the URL is the source of truth, but it updates a moment after a click. Until it does, show the
  // state just asked for, so a checkbox or menu never looks like it ignored the click.
  const urlKey = params.toString();
  const [optimistic, setOptimistic] = useState<ListState | null>(null);
  useEffect(() => setOptimistic(null), [urlKey]);
  const base: ListState = isFile ? fileState : (optimistic ?? parseUrlState(new URLSearchParams(urlKey)));
  useEffect(() => {
    const id = setTimeout(() => setTyped(search), isFile ? 0 : SEARCH_PAUSE_MS);
    return () => clearTimeout(id);
  }, [search, isFile]);
  const state: ListState = { ...base, q: typed };

  const update = useCallback(
    (patch: Partial<ListState>) => {
      const next = { ...base, ...patch, page: patch.page ?? 1 };
      if (isFile) setFileState(next);
      else {
        setOptimistic(next);
        router.replace(`${pathname}${serializeUrlState(next)}`, { scroll: false });
      }
    },
    [base, isFile, pathname, router],
  );
  const onSearch = (text: string) => {
    setSearch(text);
    if (base.page > 1) update({ page: 1 });
  };

  // --- file results: everything in the browser, no request ---------------------------------------------------
  const fileResult = useMemo(
    () => (source.kind === "file" ? applyList(source.rows, typeKey, state) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [source.kind === "file" ? source.rows : null, typeKey, state.q, state.status, state.reachable, state.sort, state.dir, state.page],
  );

  // --- saved results: one request per change, the latest wins -------------------------------------------------
  const [loaded, setLoaded] = useState<Loaded>({ kind: "loading", items: [], total: 0, first: true });
  const [retry, setRetry] = useState(0);
  const queryKey = JSON.stringify(apiParams(typeKey, state));
  useEffect(() => {
    if (source.kind !== "saved") return;
    const controller = new AbortController();
    setLoaded((prev) => ({ kind: "loading", items: prev.items, total: prev.total, first: prev.kind === "loading" && prev.first }));
    (async () => {
      try {
        const { data } = await source.client.GET("/features/reactivation/runs/{run_id}/patients", {
          params: { path: { run_id: source.runId }, query: JSON.parse(queryKey) as PatientsQuery },
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (!data) return setLoaded((prev) => ({ kind: "error", items: prev.items, total: prev.total }));
        setLoaded({ kind: "ready", items: data.items.map((p) => rowFromSaved(p, source.timeZone)), total: data.total });
      } catch {
        if (!controller.signal.aborted) setLoaded((prev) => ({ kind: "error", items: prev.items, total: prev.total }));
      }
    })();
    return () => controller.abort();
  }, [source, queryKey, retry]);

  const items = fileResult ? fileResult.items : loaded.items;
  const total = fileResult ? fileResult.total : loaded.total;
  const loading = !fileResult && loaded.kind === "loading";
  const firstLoad = !fileResult && loaded.kind === "loading" && loaded.first;
  const failed = !fileResult && loaded.kind === "error";
  const page = fileResult ? fileResult.page : state.page;

  // The page asked for is past the end (a filter shrank the list): go to the last one.
  useEffect(() => {
    if (!fileResult && loaded.kind === "ready" && loaded.items.length === 0 && loaded.total > 0 && state.page > 1)
      update({ page: clampPage(state.page, loaded.total) });
  }, [fileResult, loaded, state.page, update]);

  const filtered = isFiltered(state, typeKey);
  const onSort = (key: ListState["sort"]) =>
    update(state.sort === key ? { dir: state.dir === "desc" ? "asc" : "desc" } : { sort: key, dir: "desc" });
  const clear = () => {
    setSearch("");
    setTyped("");
    const cleared = clearFilters(state);
    if (isFile) setFileState(cleared);
    else {
      setOptimistic(cleared);
      router.replace(`${pathname}${serializeUrlState(cleared)}`, { scroll: false });
    }
    searchRef.current?.focus();
  };

  const count = loading && !items.length ? "Loading patients" : `${formatCount(total)} ${total === 1 ? "patient" : "patients"}${filtered ? " match" : ""}`;
  const pages = pageCount(total);
  const from = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(total, page * PAGE_SIZE);

  return (
    <Card>
      <div className="dp-patient-list" data-testid="patient-list">
        <PatientControls
          state={state}
          search={search}
          onSearch={onSearch}
          onChange={update}
          showStatus={hasStatusFilter(typeKey)}
          searchRef={searchRef}
        />
        <p className="dp-count" role="status" aria-live="polite" data-testid="result-count">
          {count}
        </p>

        {failed ? (
          <Notice
            tone="error"
            title="We couldn't load the patients."
            action={
              <Button variant="secondary" onClick={() => setRetry((n) => n + 1)}>
                Try again
              </Button>
            }
          >
            Your data is safe. Please try again.
          </Notice>
        ) : firstLoad ? (
          <ListSkeleton />
        ) : total === 0 && !loading ? (
          filtered ? (
            <EmptyState
              title="No patients match these filters"
              action={
                <Button variant="secondary" onClick={clear} data-testid="clear-filters">
                  Clear filters
                </Button>
              }
            >
              Try a different search, or clear the filters to see everyone in this group.
            </EmptyState>
          ) : (
            <EmptyState title="No patients in this group">
              {entry?.patient_count === 0
                ? "Nobody matched this group in the latest analysis."
                : "There's nobody to show here."}
            </EmptyState>
          )
        ) : (
          <>
            <PatientTable rows={items} sort={state.sort} dir={state.dir} onSort={onSort} busy={loading} />
            <nav className="dp-pager" aria-label="Pages of patients">
              <p className="dp-small" data-testid="page-range">
                Showing {formatCount(from)} to {formatCount(to)} of {formatCount(total)}
              </p>
              <div className="dp-pager-buttons">
                <Button variant="secondary" disabled={page <= 1} onClick={() => update({ page: page - 1 })} data-testid="page-prev">
                  Previous
                </Button>
                <span className="dp-pager-page" data-testid="page-number">
                  Page {formatCount(page)} of {formatCount(pages)}
                </span>
                <Button variant="secondary" disabled={page >= pages} onClick={() => update({ page: page + 1 })} data-testid="page-next">
                  Next
                </Button>
              </div>
            </nav>
          </>
        )}
      </div>
    </Card>
  );
}

// --- loading ------------------------------------------------------------------------------------------------------------------

function ListSkeleton() {
  return (
    <div className="dp-list-skeleton" role="status" aria-label="Loading patients" data-testid="list-skeleton">
      {Array.from({ length: 6 }, (_, i) => (
        <div key={i} className="dp-skel-row">
          <Skeleton width="28%" height={16} />
          <Skeleton width="14%" height={16} />
          <Skeleton width="12%" height={16} />
          <Skeleton width="10%" height={16} />
          <Skeleton width="14%" height={16} />
        </div>
      ))}
    </div>
  );
}

export function TypeSkeleton() {
  return (
    <div className="dp-stack" role="status" aria-label="Loading this patient group">
      <Skeleton width={140} height={14} />
      <div>
        <Skeleton width={220} height={26} />
        <div style={{ marginTop: 8 }}>
          <Skeleton width={360} height={14} />
        </div>
      </div>
      <div className="dp-tiles">
        {[0, 1, 2].map((i) => (
          <Card key={i}>
            <Skeleton width={90} height={12} />
            <div style={{ marginTop: 12 }}>
              <Skeleton width="60%" height={28} />
            </div>
          </Card>
        ))}
      </div>
      <Card>
        <ListSkeleton />
      </Card>
    </div>
  );
}
