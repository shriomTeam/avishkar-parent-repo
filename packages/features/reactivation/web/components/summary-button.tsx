"use client";
import { useRef, useState } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import type { CsvAnalysis } from "../lib/api-types";
import { browserClient } from "../lib/client";
import { downloadBytes } from "../lib/download";
import { clinicOf } from "../lib/profile";
import { today } from "../lib/report-data";
import { buildSummaryPdf, summaryFileName, summaryFromFile, summaryFromSaved } from "../lib/summary-pdf";
import { Button, Icon } from "./kit";

type Source =
  | { kind: "saved"; runId: string; dormant: number | null }
  | { kind: "file"; data: CsvAnalysis; dormant: number | null };

/**
 * Downloads the summary report as a PDF. Saved results come from the summary endpoint (counts and totals, one audited
 * call); file results are already in this tab's memory and are never sent anywhere. Either way the PDF is built here.
 */
export function SummaryReportButton({ source }: { source: Source }) {
  const { auth } = useAuth();
  const [state, setState] = useState<"idle" | "building" | "error">("idle");
  const busy = useRef(false);
  const timeZone = auth.workspace?.timezone ?? "America/New_York";
  const clinic = clinicOf(auth.workspace?.name).name;
  const empty = source.dormant === 0;

  async function run() {
    if (busy.current || empty) return;
    busy.current = true;
    setState("building");
    try {
      await new Promise((resolve) => setTimeout(resolve, 0)); // let "Building PDF…" show before the work starts
      const day = today(timeZone);
      let input;
      if (source.kind === "saved") {
        const client = browserClient(auth.csrf_token, auth.workspace?.id);
        const { data, response } = await client.GET("/features/reactivation/runs/{run_id}/summary", {
          params: { path: { run_id: source.runId } },
        });
        if (!data || !response.ok) throw new Error("summary request failed");
        input = summaryFromSaved({ clinic, today: day, timeZone, data });
      } else {
        input = summaryFromFile({ clinic, today: day, data: source.data });
      }
      const bytes = buildSummaryPdf(input) as Uint8Array<ArrayBuffer>;
      downloadBytes(bytes, summaryFileName(day, source.kind), "application/pdf");
      setState("idle");
    } catch {
      setState("error");
    } finally {
      busy.current = false;
    }
  }

  return (
    <>
      <Button
        variant="secondary"
        onClick={run}
        aria-disabled={state === "building" || empty || undefined}
        aria-busy={state === "building" || undefined}
        data-testid="summary-report"
      >
        {state === "building" ? (
          "Building PDF…"
        ) : (
          <>
            <Icon name="file" size={16} />
            Download summary report
          </>
        )}
      </Button>
      {empty && (
        <span className="dp-small" data-testid="summary-empty">
          No patients to report
        </span>
      )}
      {state === "error" && (
        <span className="dp-small dp-export-error" role="alert" data-testid="summary-error">
          We couldn&apos;t build the report. Please try again.
        </span>
      )}
    </>
  );
}
