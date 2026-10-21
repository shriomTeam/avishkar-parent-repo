"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@clinic/core/web/auth/provider";

import type { LatestRun, TypeEntry } from "../lib/api-types";
import { browserClient } from "../lib/client";
import { formatDateTime, relativeTime } from "../lib/format";
import { failureMessage, stageLabel } from "../lib/messages";
import { canRunRole } from "../lib/roles";
import { num } from "../lib/summary";
import { useCsvResult } from "./csv-provider";
import { CsvResults } from "./csv-results";
import { ExportReportButton } from "./export-button";
import { Button, ButtonLink, Card, EmptyState, Icon, Notice, ProgressBar } from "./kit";
import { QualityPanel } from "./quality-panel";
import { Tiles } from "./tiles";
import { TypesTable } from "./types-table";
import { IMPORT_PATH } from "./shell-nav";
import { Welcome } from "./welcome";

export type InFlight = { id: string; status: string; progress_pct: number };
export type OverviewData = {
  latest: LatestRun | null;
  /** The version of the settings saved now, or null when it could not be read. */
  currentSettingsVersion: number | null;
  types: TypeEntry[];
  inFlight: InFlight | null;
  /** The newest run failed and nothing newer is running. */
  failedCode: string | null | undefined;
  /** No patient data and no completed analysis: show the welcome page instead of an empty Overview. */
  welcome: boolean;
};

const POLL_MS = 2000;

function idempotencyKey() {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function Overview({ data }: { data: OverviewData }) {
  const { auth } = useAuth();
  const router = useRouter();
  const tenantId = auth.workspace?.id;
  const timeZone = auth.workspace?.timezone ?? "America/New_York";
  const role = auth.memberships.find((m) => m.workspace_id === tenantId)?.role;
  const canRun = canRunRole(role);
  const client = useMemo(
    () => browserClient(auth.csrf_token, tenantId),
    [auth.csrf_token, tenantId],
  );

  const [run, setRun] = useState<InFlight | null>(data.inFlight);
  const [failed, setFailed] = useState<{ code: string | null } | null>(
    data.failedCode === undefined ? null : { code: data.failedCode },
  );
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [trouble, setTrouble] = useState(false);
  const [now, setNow] = useState<Date | null>(null);
  const { result: csv } = useCsvResult();
  const params = useSearchParams();
  const forceSaved = params.get("view") === "saved";
  const [cleared, setCleared] = useState(false);

  // Arriving from a type page whose file results were lost to a refresh: say so once, then tidy the address.
  useEffect(() => {
    if (params.get("notice") === "file-cleared") {
      setCleared(true);
      router.replace("/reactivation");
    }
  }, [params, router]);

  useEffect(() => {
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const runId = run?.id;
  const clientRef = useRef(client);
  clientRef.current = client;
  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      if (cancelled) return;
      if (document.hidden) {
        timer = setTimeout(tick, POLL_MS);
        return;
      }
      try {
        const { data: detail } = await clientRef.current.GET(
          "/features/reactivation/runs/{run_id}",
          { params: { path: { run_id: runId } } },
        );
        if (cancelled) return;
        if (!detail) throw new Error("no data");
        setTrouble(false);
        if (detail.status === "completed") {
          setRun(null);
          router.refresh();
          return;
        }
        if (detail.status === "failed" || detail.status === "cancelled") {
          setRun(null);
          setFailed({ code: detail.error_code });
          return;
        }
        setRun({
          id: runId,
          status: detail.status,
          progress_pct: detail.progress_pct,
        });
      } catch {
        if (!cancelled) setTrouble(true);
      }
      if (!cancelled) timer = setTimeout(tick, POLL_MS);
    };
    void tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [runId, router]);

  async function runNow() {
    setStarting(true);
    setStartError(null);
    setFailed(null);
    try {
      const { data: started, response } = await client.POST(
        "/features/reactivation/runs",
        { params: { header: { "idempotency-key": idempotencyKey() } } },
      );
      if (!started) {
        setStartError(
          response.status === 403
            ? "Your role can't start an analysis. Ask the clinic owner or office manager."
            : response.status === 429
              ? "You've started a lot of analyses today. Please try again tomorrow."
              : "We couldn't start the analysis. Please try again in a moment.",
        );
        return;
      }
      setRun({
        id: started.id,
        status: started.status,
        progress_pct: started.progress_pct,
      });
    } catch {
      setStartError("We couldn't reach the server. Check your connection and try again.");
    } finally {
      setStarting(false);
    }
  }

  // File results replace the page body but not this component, so a run in flight keeps polling underneath.
  if (csv && !forceSaved)
    return (
      <CsvResults
        result={csv}
        canImport={canRun}
        timeZone={timeZone}
        onBack={() => router.refresh()}
      />
    );
  const clearedNotice = cleared ? (
    <Notice tone="info" title="Your file results were cleared.">
      They were only held in this tab, so a refresh removes them. Nothing from the file was saved.
      {canRun ? " Import the file again to see them." : ""}
    </Notice>
  ) : null;
  if (data.welcome) return <Welcome canImport={canRun} notice={clearedNotice} />;

  const { latest, types } = data;
  const busy = starting || run !== null;
  const summary = latest?.summary ?? null;
  const runButton = canRun ? (
    <Button onClick={runNow} disabled={busy} data-testid="run-now">
      {!busy && <Icon name="play" size={16} />}
      {busy ? "Analysing…" : latest ? "Run now" : "Analyse my patients"}
    </Button>
  ) : null;
  const importButton = canRun ? (
    <ButtonLink variant="secondary" href={IMPORT_PATH} data-testid="import-csv">
      <Icon name="upload" size={16} />
      Import CSV
    </ButtonLink>
  ) : null;

  const exportButton =
    canRun && latest ? (
      <ExportReportButton source={{ kind: "saved", latest, types, dormant: num(summary, "dormant_count") }} />
    ) : null;

  return (
    <div className="dp-stack">
      {clearedNotice}
      {csv && forceSaved && (
        <Notice
          tone="info"
          title="File results are open in this tab."
          action={
            <button type="button" className="dp-link-button" onClick={() => router.replace("/reactivation")} data-testid="view-file-results">
              View file results
            </button>
          }
        >
          What you see below is your saved data.
        </Notice>
      )}
      <div className="dp-head">
        <div>
          <h1 className="dp-title">Overview</h1>
          <p className="dp-sub" data-testid="last-analysed">
            {latest?.finished_at ? (
              <>
                Last analysed{" "}
                <abbr title={formatDateTime(latest.finished_at, timeZone)}>
                  {now
                    ? relativeTime(latest.finished_at, now)
                    : formatDateTime(latest.finished_at, timeZone)}
                </abbr>
              </>
            ) : (
              "Not analysed yet"
            )}
          </p>
        </div>
        {(importButton || exportButton || (latest && runButton)) && (
          <div className="dp-head-actions">
            {importButton}
            {exportButton}
            {latest && runButton}
          </div>
        )}
      </div>

      {startError && <Notice tone="error">{startError}</Notice>}
      {failed && !run && (
        <Notice tone="error" title="The last analysis didn't finish.">
          {failureMessage(failed.code)}
        </Notice>
      )}
      {run && <ProgressCard run={run} trouble={trouble} />}
      {latest && !run && data.currentSettingsVersion !== null && latest.settings_version !== data.currentSettingsVersion && (
        <Notice tone="info" title="Your settings changed after this analysis." >
          {canRun
            ? "The figures below still use the earlier settings. Run the analysis again to use the new ones."
            : "The figures below still use the earlier settings. The clinic owner or office manager can run the analysis again."}
        </Notice>
      )}

      {!latest ? (
        run ? null : (
          <Card>
            <EmptyState
              title="Find the patients who've gone quiet"
              action={runButton}
            >
              {canRun
                ? "We'll look through your patient records, work out who is overdue to come back, and estimate what they could be worth. It usually takes a minute or two."
                : "Your clinic hasn't run its first analysis yet. The clinic owner or office manager can start one from this page."}
            </EmptyState>
          </Card>
        )
      ) : (
        <>
          <Tiles summary={summary} />
          <Card title="Patient types">
            {types.length === 0 ? (
              <EmptyState title="No patient types to show">
                Every patient type is switched off. Turn some on in Settings and
                run the analysis again.
              </EmptyState>
            ) : (
              <TypesTable types={types} />
            )}
          </Card>
          <QualityPanel quality={latest.quality} />
        </>
      )}
    </div>
  );
}

function ProgressCard({ run, trouble }: { run: InFlight; trouble: boolean }) {
  const stage = stageLabel(run.status, run.progress_pct);
  return (
    <Card>
      <div data-testid="progress-card" aria-live="polite">
        <div className="dp-progress-row">
          <strong>Analysis in progress</strong>
          <span>{run.status === "queued" ? "Queued" : `${run.progress_pct}%`}</span>
        </div>
        <ProgressBar value={run.progress_pct} label="Analysis progress" />
        <p className="dp-hint" data-testid="progress-stage">
          {stage}. You can leave this page; the analysis keeps going.
        </p>
        {trouble && (
          <div style={{ marginTop: 12 }}>
            <Notice tone="warn">
              We can&apos;t check on the analysis right now. We&apos;ll keep
              trying.
            </Notice>
          </div>
        )}
      </div>
    </Card>
  );
}
