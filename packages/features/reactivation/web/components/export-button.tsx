"use client";
import { useRef, useState } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import type { CsvAnalysis, LatestRun, TypeEntry } from "../lib/api-types";
import { browserClient } from "../lib/client";
import { downloadBytes } from "../lib/download";
import { buildReport, reportFileName } from "../lib/report";
import { reportFromFile, reportFromSaved, today } from "../lib/report-data";
import { clinicOf } from "../lib/profile";
import { Button, Icon } from "./kit";

const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

type Source =
  | { kind: "saved"; latest: Pick<LatestRun, "id" | "finished_at" | "summary">; types: TypeEntry[]; dormant: number | null }
  | { kind: "file"; fileName: string; data: CsvAnalysis; dormant: number | null };

/**
 * Downloads the report as a spreadsheet. Saved results are read from the report endpoint (one audited call);
 * file results are already in this tab's memory and are never sent anywhere. Either way the file is built here.
 */
export function ExportReportButton({ source }: { source: Source }) {
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
      await new Promise((resolve) => setTimeout(resolve, 0)); // let "Building report…" show before the work starts
      let input;
      if (source.kind === "saved") {
        const client = browserClient(auth.csrf_token, auth.workspace?.id);
        const { data, response } = await client.GET("/features/reactivation/runs/{run_id}/report", {
          params: { path: { run_id: source.latest.id } },
        });
        if (!data || !response.ok) throw new Error("report request failed");
        input = reportFromSaved({ clinic, timeZone, latest: source.latest, types: source.types, patients: data.patients });
      } else {
        input = reportFromFile({ clinic, timeZone, fileName: source.fileName, data: source.data });
      }
      const bytes = buildReport(input) as Uint8Array<ArrayBuffer>;
      downloadBytes(bytes, reportFileName(today(timeZone), source.kind === "saved" ? "saved" : "file"), XLSX);
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
        data-testid="export-report"
      >
        {state === "building" ? "Building report…" : (
          <>
            <Icon name="download" size={16} />
            Export report
          </>
        )}
      </Button>
      {empty && (
        <span className="dp-small" data-testid="export-empty">
          No patients to export
        </span>
      )}
      {state === "error" && (
        <span className="dp-small dp-export-error" role="alert" data-testid="export-error">
          We couldn&apos;t build the report. Please try again.
        </span>
      )}
    </>
  );
}
