/**
 * The summary report as a PDF: how many patients are dormant and what that could be worth, by patient group. Totals
 * only, with no patient names, contact details or file names. One builder serves saved results and a file analysis.
 */
import type { Schemas } from "@clinic/api-client";

import type { CsvAnalysis, TypeEntry } from "./api-types";
import { formatCount, formatMoney, formatRange, formatRateRange, rateBasisText } from "./format";
import { NOT_SIZED, unavailableReason } from "./messages";
import { decodeBase64, Flow, hex, PAGE, PdfDocument, readPng, textWidth, wrap, type Cell, type Page } from "./pdf";
import { REPORT_BRAND_NAME, REPORT_FOOTER_TEXT, REPORT_PRIVACY_LINE } from "./pdf-brand";
import { REPORT_LOGO_PNG_BASE64 } from "./pdf-logo";
import { dayIn } from "./report";
import { type Config, GROUPS } from "./settings";
import { num } from "./summary";

export type SummaryOut = Schemas["SummaryOut"];

export type SummaryGroup = {
  key: string;
  label: string;
  available: boolean;
  patients: number | null;
  /** "new", "retention" or null (unclassified). */
  kind: string | null;
  lowCents: number | null;
  highCents: number | null;
  rateLow: number | null;
  rateHigh: number | null;
  rateSource: string | null;
};

export type SummaryInput = {
  clinic: string;
  /** "2026-10-21", the day the report is made in the clinic's time zone. */
  generatedOn: string;
  source: { kind: "saved"; day: string | null } | { kind: "file" };
  dormant: number | null;
  patients: number | null;
  lowCents: number | null;
  highCents: number | null;
  groups: SummaryGroup[];
  settings: Config;
  /** 0 means the standard settings. */
  settingsVersion: number;
};

// --- colours: the same tokens as the app (reactivation.css), all at least 4.5:1 on white ---------------------------
const INK = hex("#201d1d");
const MUTED = hex("#5e5b68");
const RULE = hex("#c9c7cf");
const HEAD_FILL = hex("#f1f0f3");
const TILE_FILL = hex("#f6fff0");
const TILE_EDGE = hex("#568f29");
const INFO_FILL = hex("#f0f6ff");
const INFO_EDGE = hex("#2f5fa8");
const INFO_INK = hex("#1e3a5f");

/** The colours the report uses, so a test can check their contrast. */
export const PDF_COLORS = { INK, MUTED, HEAD_FILL, TILE_FILL, INFO_FILL, INFO_INK } as const;

const LEFT = 54;
const RIGHT = PAGE.width - 54;
const HEADER_RULE_Y = PAGE.height - 72;
const BODY_TOP = HEADER_RULE_Y - 20;
const FOOTER_RULE_Y = 78;
const BODY_BOTTOM = FOOTER_RULE_Y + 16;
const LOGO_SIZE = 34;

export const SUMMARY_TITLE = "Dormant patients: summary report";
export const HOW_ESTIMATED =
  "For each dormant patient we take what that patient usually spends and multiply it by a range of how often patients like them come back. The range is assumed, or measured from your own past campaigns where there are enough of them. These figures are estimates based on your clinic's own history, not forecasts, and actual results may be higher or lower. A patient is counted in one group only.";
export const FILE_NOTE =
  "These figures come from an imported file that was not saved. They were worked out in your browser and are not stored anywhere, so they won't appear in your saved analyses. Return rates are assumed.";
export const REVENUE_HINT = "New revenue if some of them come back. Prepaid balances aren't included.";

export function summaryFileName(day: string, mode: "saved" | "file"): string {
  return `dormant-patients-summary-${day}-${mode === "saved" ? "saved" : "from-file"}.pdf`;
}

/** "2026-10-21" as "October 21, 2026". */
export function longDay(day: string): string {
  const [y, m, d] = day.split("-").map(Number);
  if (!y || !m || !d) return day;
  return new Intl.DateTimeFormat("en-US", { timeZone: "UTC", year: "numeric", month: "long", day: "numeric" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

/** The settings, one plain sentence each. The dollar cutoff appears only when it is set. */
export function settingsLines(settings: Config): string[] {
  const lhv = settings.types.lapsed_high_value;
  const top = `Top spenders: the top ${100 - lhv.spend_percentile_min}% of patients by spend${
    lhv.spend_cents_min == null ? "" : `, and anyone who has spent more than ${formatMoney(lhv.spend_cents_min)} in total`
  }.`;
  const lines = [
    `Dormant after ${formatCount(settings.dormant.min_days_since_visit)} days without a visit, or after a patient's usual time between visits if that is shorter.`,
    `Usual time between visits: ${formatCount(settings.dormant.default_rebooking_days)} days.`,
    `Patients who came once: dormant after ${formatCount(settings.types.one_and_done.min_days_since_visit)} days.`,
    top,
    `Churned members: ${formatCount(settings.types.churned_member.membership_months)} months of their membership fee counted.`,
    `Return rate: an assumed range of ${formatRateRange(settings.revenue.rate_low, settings.revenue.rate_high)}, used where your own past campaigns don't give a measured rate.`,
  ];
  const off = GROUPS.filter((g) => !settings.types[g.key].enabled).map((g) => g.label);
  if (off.length) lines.push(`Patient types switched off: ${off.join(", ")}.`);
  return lines;
}

export const settingsHeading = (version: number) =>
  version ? `Your saved settings (version ${version})` : "The standard settings";

function groupRows(groups: SummaryGroup[], source: "saved" | "file"): Cell[][] {
  const small = { size: 8.5, color: MUTED };
  return groups.map((g) => {
    const first: Cell = { lines: [{ text: g.label, font: "bold" }] };
    let patients: Cell;
    let revenue: Cell;
    if (!g.available) {
      first.lines.push({ text: unavailableReason(g.key, source), ...small });
      patients = { lines: [{ text: "Not available" }], align: "right" };
      revenue = { lines: [{ text: "Not available" }] };
    } else {
      patients = { lines: [{ text: g.patients === null ? "Not available" : formatCount(g.patients) }], align: "right" };
      if (g.key === "unclassified") {
        revenue = { lines: [{ text: "No estimate" }, { text: NOT_SIZED.unclassified, ...small }] };
      } else if (g.kind === "retention") {
        first.lines.push({ text: "Prepaid balance: not counted as new revenue", ...small });
        revenue = {
          lines: [{ text: `${formatMoney(g.lowCents ?? 0)} already paid` }, { text: "Not new revenue, so it isn't in the total.", ...small }],
        };
      } else if (g.lowCents === null || g.highCents === null) {
        revenue = { lines: [{ text: "Not available" }] };
      } else {
        revenue = { lines: [{ text: formatRange(g.lowCents, g.highCents), font: "bold" }] };
        if (g.rateLow !== null && g.rateHigh !== null && g.rateSource)
          revenue.lines.push({ text: rateBasisText(g.rateSource, g.rateLow, g.rateHigh), ...small });
      }
    }
    return [first, patients, revenue];
  });
}

function tile(flow: Flow, x: number, width: number, top: number, height: number, label: string, value: string, hint: string) {
  const page = flow.page;
  page.rect(x, top - height, width, height, { fill: TILE_FILL, stroke: TILE_EDGE, width: 0.75 });
  page.text(label, x + 10, top - 18, { font: "bold", size: 9.5, color: MUTED });
  page.text(value, x + 10, top - 42, { font: "bold", size: 19, color: INK });
  let y = top - 58;
  for (const line of wrapHint(hint, width - 20)) {
    page.text(line, x + 10, y, { size: 8.5, color: MUTED });
    y -= 11.5;
  }
}

const wrapHint = (text: string, width: number) => wrap(text, "regular", 8.5, width);

function decorate(page: Page, index: number, total: number, logoReady: boolean) {
  if (logoReady) page.image(LEFT, PAGE.height - 40 - LOGO_SIZE, LOGO_SIZE, LOGO_SIZE);
  page.text(REPORT_BRAND_NAME, LEFT + LOGO_SIZE + 10, PAGE.height - 40 - LOGO_SIZE / 2 - 5, { font: "bold", size: 15, color: INK });
  page.line(LEFT, HEADER_RULE_Y, RIGHT, HEADER_RULE_Y, { color: RULE, width: 0.75 });

  page.line(LEFT, FOOTER_RULE_Y, RIGHT, FOOTER_RULE_Y, { color: RULE, width: 0.75 });
  let y = FOOTER_RULE_Y - 12;
  for (const line of wrap(REPORT_PRIVACY_LINE, "regular", 7.5, RIGHT - LEFT)) {
    page.text(line, LEFT, y, { size: 7.5, color: MUTED });
    y -= 10;
  }
  const label = `Page ${index + 1} of ${total}`;
  page.text(REPORT_FOOTER_TEXT, LEFT, 30, { size: 8, color: INK });
  page.text(label, RIGHT - textWidth(label, "regular", 8), 30, { size: 8, color: INK });
}

export function buildSummaryPdf(input: SummaryInput, when: Date = new Date()): Uint8Array {
  const logo = readPng(decodeBase64(REPORT_LOGO_PNG_BASE64));
  const doc = new PdfDocument({ title: SUMMARY_TITLE, creator: REPORT_BRAND_NAME, created: when, logo });
  const flow = new Flow(doc, { left: LEFT, right: RIGHT, top: BODY_TOP, bottom: BODY_BOTTOM });
  const source = input.source.kind === "file" ? "file" : "saved";

  flow.paragraph(SUMMARY_TITLE, { font: "bold", size: 20, color: INK });
  flow.gap(6);
  flow.paragraph(input.clinic, { font: "bold", size: 12, color: INK });
  flow.paragraph(`Prepared on ${longDay(input.generatedOn)}`, { size: 10, color: MUTED });
  flow.paragraph(
    input.source.kind === "file"
      ? "Source: a CSV file imported in your browser. It was not saved."
      : input.source.day
        ? `Source: your saved analysis from ${longDay(input.source.day)}.`
        : "Source: your saved analysis.",
    { size: 10, color: MUTED },
  );
  flow.gap(12);

  if (input.source.kind === "file") {
    flow.box(FILE_NOTE, { fill: INFO_FILL, stroke: INFO_EDGE, color: INFO_INK, title: "This report is from an imported file." });
    flow.gap(12);
  }

  const width = (flow.width - 14) / 2;
  const height = 76;
  flow.need(height);
  const top = flow.y;
  tile(
    flow,
    LEFT,
    width,
    top,
    height,
    "Dormant patients",
    input.dormant === null ? "Not available" : formatCount(input.dormant),
    input.patients === null ? "" : `of ${formatCount(input.patients)} ${input.patients === 1 ? "patient" : "patients"}`,
  );
  tile(
    flow,
    LEFT + width + 14,
    width,
    top,
    height,
    "Recoverable revenue",
    input.lowCents === null || input.highCents === null ? "Not available" : formatRange(input.lowCents, input.highCents),
    REVENUE_HINT,
  );
  flow.y = top - height;
  flow.gap(18);

  flow.need(120);
  flow.paragraph("By patient group", { font: "bold", size: 13, color: INK });
  flow.gap(4);
  const rows = groupRows(input.groups, source);
  rows.push([
    { lines: [{ text: "All groups", font: "bold" }] },
    { lines: [{ text: input.dormant === null ? "Not available" : formatCount(input.dormant), font: "bold" }], align: "right" },
    {
      lines: [
        {
          text: input.lowCents === null || input.highCents === null ? "Not available" : formatRange(input.lowCents, input.highCents),
          font: "bold",
        },
        { text: "Prepaid balance isn't included.", size: 8.5, color: MUTED },
      ],
    },
  ]);
  flow.table(
    [{ width: 200 }, { width: 70, align: "right" }, { width: flow.width - 270 }],
    ["Patient group", "Patients", "Recoverable revenue (estimate)"],
    rows,
    { headFill: HEAD_FILL, rule: RULE, headColor: INK },
  );
  flow.gap(18);

  flow.need(90);
  flow.paragraph("Settings used", { font: "bold", size: 13, color: INK });
  flow.gap(2);
  flow.paragraph(`${settingsHeading(input.settingsVersion)}:`, { size: 10, color: INK });
  for (const line of settingsLines(input.settings))
    flow.paragraph(`•  ${line}`, { size: 9.5, color: INK, x: LEFT + 6 });
  flow.gap(14);

  flow.need(90);
  flow.paragraph("How these figures are estimated", { font: "bold", size: 13, color: INK });
  flow.gap(2);
  flow.paragraph(HOW_ESTIMATED, { size: 9.5, color: INK });

  return doc.build((page, i, total) => decorate(page, i, total, true));
}

// --- from the two sources ----------------------------------------------------------------------------------------

function groups(types: TypeEntry[]): SummaryGroup[] {
  return types.map((t) => ({
    key: t.type_key,
    label: t.label,
    available: t.available,
    patients: t.patient_count,
    kind: t.kind,
    lowCents: t.revenue_low_cents,
    highCents: t.revenue_high_cents,
    rateLow: t.rate_low,
    rateHigh: t.rate_high,
    rateSource: t.rate_source,
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

export function summaryFromSaved(args: { clinic: string; today: string; timeZone: string; data: SummaryOut }): SummaryInput {
  const { data } = args;
  return {
    clinic: args.clinic,
    generatedOn: args.today,
    source: { kind: "saved", day: data.finished_at ? dayIn(args.timeZone)(data.finished_at) : null },
    ...totals(data.summary),
    groups: groups(data.types),
    settings: data.settings as Config,
    settingsVersion: data.settings_version,
  };
}

export function summaryFromFile(args: { clinic: string; today: string; data: CsvAnalysis }): SummaryInput {
  const { data } = args;
  return {
    clinic: args.clinic,
    generatedOn: args.today,
    source: { kind: "file" },
    ...totals(data.summary),
    groups: groups(data.types),
    settings: data.settings as Config,
    settingsVersion: data.settings_version,
  };
}
