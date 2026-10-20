/** Turns what the screen already holds into the input of the report: saved results, or file results in memory. */
import type { Schemas } from "@clinic/api-client";

import type { CsvAnalysis, LatestRun, TypeEntry } from "./api-types";
import { BAND_LABEL, likelihoodBand } from "./patient-list";
import { dayIn, type ReportInput, type ReportRow, type ReportType } from "./report";
import { num } from "./summary";

export type ReportPatient = Schemas["ReportPatient"];

const UNCLASSIFIED = "unclassified";

function reportTypes(types: TypeEntry[]): ReportType[] {
  return types.map((t) => ({
    key: t.type_key,
    label: t.label,
    description: t.description,
    available: t.available,
    patients: t.patient_count,
    lowCents: t.revenue_low_cents,
    highCents: t.revenue_high_cents,
    topService: t.top_service_name,
  }));
}

function totals(summary: Record<string, unknown> | null | undefined) {
  return {
    dormant: num(summary, "dormant_count"),
    patients: num(summary, "patients_total"),
    lowCents: num(summary, "new_revenue_low_cents"),
    highCents: num(summary, "new_revenue_high_cents"),
  };
}

function band(score: number | null): string {
  const b = likelihoodBand(score);
  return b ? BAND_LABEL[b] : "";
}

function add(rows: Map<string, ReportRow[]>, key: string | null, row: ReportRow) {
  const k = key ?? UNCLASSIFIED;
  const list = rows.get(k);
  if (list) list.push(row);
  else rows.set(k, [row]);
}

/** The day the report is made, in the clinic's time zone. */
export function today(timeZone: string): string {
  return dayIn(timeZone)(new Date().toISOString()) ?? new Date().toISOString().slice(0, 10);
}

export function reportFromSaved(args: {
  clinic: string;
  timeZone: string;
  latest: Pick<LatestRun, "finished_at" | "summary">;
  types: TypeEntry[];
  patients: ReportPatient[];
}): ReportInput {
  const rows = new Map<string, ReportRow[]>();
  const dayOf = dayIn(args.timeZone);
  for (const p of args.patients) {
    if (p.status !== "dormant") continue;
    add(rows, p.primary_type, {
      id: p.patient_id,
      name: p.display_name?.trim() || `Patient ${p.patient_id.slice(0, 8)}`,
      status: p.status,
      usualService: p.usual_service_name,
      lastVisitDay: p.last_visit_at ? dayOf(p.last_visit_at) : null,
      daysSince: p.days_since_last_visit,
      likelihood: band(p.likelihood_score),
      score: p.likelihood_score,
      basisCents: p.revenue_basis_cents,
      lowCents: p.revenue_low_cents,
      highCents: p.revenue_high_cents,
      offerService: p.offer_service_name,
      reasons: p.reasons,
    });
  }
  const day = args.latest.finished_at ? dayOf(args.latest.finished_at) : null;
  return {
    clinic: args.clinic,
    generatedOn: today(args.timeZone),
    source: day ? `Saved analysis from ${day}` : "Saved analysis",
    totals: totals(args.latest.summary),
    types: reportTypes(args.types),
    rows,
  };
}

export function reportFromFile(args: { clinic: string; timeZone: string; fileName: string; data: CsvAnalysis }): ReportInput {
  const rows = new Map<string, ReportRow[]>();
  for (const p of args.data.patients) {
    if (p.status !== "dormant") continue;
    add(rows, p.primary_type, {
      id: p.external_id,
      name: p.display_name?.trim() || `Patient ${p.external_id}`,
      status: p.status,
      usualService: p.usual_service_name,
      lastVisitDay: p.last_visit_day,
      daysSince: p.days_since_last_visit,
      likelihood: band(p.likelihood_score),
      score: p.likelihood_score,
      basisCents: p.revenue_basis_cents,
      lowCents: p.revenue_low_cents,
      highCents: p.revenue_high_cents,
      offerService: p.offer_service_name,
      reasons: p.reasons,
    });
  }
  return {
    clinic: args.clinic,
    generatedOn: today(args.timeZone),
    source: `File ${args.fileName}, not saved`,
    totals: totals(args.data.summary),
    types: reportTypes(args.data.types),
    rows,
  };
}
