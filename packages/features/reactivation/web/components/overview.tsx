"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Card, Stat } from "@clinic/ui";
import { useAuth } from "@clinic/core/web/auth/provider";

import type { LatestRun, TypeEntry } from "../lib/api-types";
import { browserClient } from "../lib/client";
import {
  formatCount,
  formatDateTime,
  formatRange,
  relativeTime,
} from "../lib/format";
import { failureMessage, stageLabel } from "../lib/messages";
import { num } from "../lib/summary";
import { EmptyState, Notice, ProgressBar } from "./kit";
import { QualityPanel } from "./quality-panel";
import { TypesTable } from "./types-table";

export type InFlight = { id: string; status: string; progress_pct: number };
export type OverviewData = {
  latest: LatestRun | null;
  types: TypeEntry[];
  inFlight: InFlight | null;
  /** The newest run failed and nothing newer is running. */
  failedCode: string | null | undefined;
};

const POLL_MS = 2000;
const CAN_RUN = new Set(["owner", "office_manager"]);

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
  const canRun = !!role && CAN_RUN.has(role);
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

  const { latest, types } = data;
  const busy = starting || run !== null;
  const summary = latest?.summary ?? null;
  const runButton = canRun ? (
    <Button onClick={runNow} disabled={busy} data-testid="run-now">
      {busy ? "Analysing…" : latest ? "Run now" : "Analyse my patients"}
    </Button>
  ) : null;

  return (
    <div className="dp-stack">
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
        {latest && runButton}
      </div>

      {startError && <Notice tone="error">{startError}</Notice>}
      {failed && !run && (
        <Notice tone="error" title="The last analysis didn't finish.">
          {failureMessage(failed.code)}
        </Notice>
      )}
      {run && <ProgressCard run={run} trouble={trouble} />}

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

function Tiles({ summary }: { summary: Record<string, unknown> | null }) {
  const dormant = num(summary, "dormant_count");
  const total = num(summary, "patients_total");
  const low = num(summary, "new_revenue_low_cents");
  const high = num(summary, "new_revenue_high_cents");
  const firstRun = summary?.first_run === true;
  const newly = num(summary, "newly_dormant");
  const back = num(summary, "returned_since_last");
  return (
    <div className="dp-tiles" data-testid="tiles">
      <div data-testid="tile-dormant">
        <Stat
          label="Dormant patients"
          value={dormant === null ? "Not available" : formatCount(dormant)}
          hint={
            total === null
              ? undefined
              : `of ${formatCount(total)} ${total === 1 ? "patient" : "patients"}`
          }
        />
      </div>
      <div data-testid="tile-revenue">
        <Stat
          label="Recoverable revenue"
          value={
            low === null || high === null
              ? "Not available"
              : formatRange(low, high)
          }
          hint="New revenue if some of them come back. Prepaid balances aren't included."
        />
      </div>
      <div data-testid="tile-change">
        <Stat
          label="Since last run"
          value={
            firstRun
              ? "First analysis"
              : newly === null
                ? "Not available"
                : `${formatCount(newly)} newly dormant`
          }
          hint={
            firstRun
              ? "There's no earlier analysis to compare with yet."
              : back === null
                ? undefined
                : `${formatCount(back)} came back`
          }
        />
      </div>
    </div>
  );
}
