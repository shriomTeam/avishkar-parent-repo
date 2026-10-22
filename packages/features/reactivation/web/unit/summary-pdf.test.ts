import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { formatCount, formatMoney, formatRange } from "../lib/format.ts";
import { PdfDocument, readPng, decodeBase64, simplify, textWidth, wrap } from "../lib/pdf.ts";
import { REPORT_BRAND_NAME, REPORT_FOOTER_TEXT, REPORT_PRIVACY_LINE } from "../lib/pdf-brand.ts";
import { REPORT_LOGO_PNG_BASE64 } from "../lib/pdf-logo.ts";
import { reportFromSaved } from "../lib/report-data.ts";
import { reportSheets } from "../lib/report.ts";
import type { Config } from "../lib/settings.ts";
import {
  FILE_NOTE,
  HOW_ESTIMATED,
  buildSummaryPdf,
  settingsLines,
  summaryFileName,
  summaryFromFile,
  summaryFromSaved,
  type SummaryGroup,
  type SummaryInput,
  type SummaryOut,
} from "../lib/summary-pdf.ts";

// --- a reader for what the writer wrote, written separately from it --------------------------------------------------

type ParsedPage = { ops: string; text: string[]; drawsLogo: boolean };

function unescape(literal: string): string {
  return literal.replace(/\\([0-7]{3}|.)/g, (_, c: string) => (c.length === 3 ? String.fromCharCode(parseInt(c, 8)) : c));
}

function parsePdf(bytes: Uint8Array) {
  const raw = Buffer.from(bytes).toString("latin1");
  assert.ok(raw.startsWith("%PDF-1.4\n"), "header");
  assert.ok(raw.endsWith("%%EOF\n"), "end marker");
  // The cross-reference table: every offset must land on "<n> 0 obj".
  const startxref = Number(/startxref\n(\d+)\n%%EOF\n$/.exec(raw)![1]);
  assert.ok(raw.startsWith("xref\n", startxref), "startxref points at the table");
  const head = /^xref\n0 (\d+)\n/.exec(raw.slice(startxref))!;
  const count = Number(head[1]);
  const entries = raw.slice(startxref + head[0].length).split("\n").slice(0, count);
  assert.equal(entries[0], "0000000000 65535 f ");
  for (let id = 1; id < count; id++) {
    const entry = entries[id]!;
    assert.equal(entry.length, 19, "an entry is 20 bytes with its newline");
    assert.ok(raw.startsWith(`${id} 0 obj\n`, Number(entry.slice(0, 10))), `object ${id} is at its offset`);
  }
  assert.match(raw, new RegExp(`/Size ${count} `));
  // Pages, in order, with their content.
  const objects = new Map<number, string>();
  for (const m of raw.matchAll(/(\d+) 0 obj\n([\s\S]*?)\nendobj\n/g)) objects.set(Number(m[1]), m[2]!);
  const kids = /\/Kids \[([^\]]*)\]/.exec(objects.get(2)!)![1]!.match(/\d+(?= 0 R)/g)!.map(Number);
  const pages: ParsedPage[] = kids.map((id) => {
    const contentId = Number(/\/Contents (\d+) 0 R/.exec(objects.get(id)!)![1]);
    const stream = /stream\n([\s\S]*)\nendstream/.exec(objects.get(contentId)!)![1]!;
    assert.equal(Number(/\/Length (\d+)/.exec(objects.get(contentId)!)![1]), stream.length, "stream length");
    const text = [...stream.matchAll(/\(((?:\\.|[^\\)])*)\) Tj/g)].map((m) => unescape(m[1]!));
    return { ops: stream, text, drawsLogo: /\/Im1 Do/.test(stream) };
  });
  assert.equal(Number(/\/Count (\d+)/.exec(objects.get(2)!)![1]), pages.length);
  return { raw, pages, objects };
}

// --- sample data, in the shape the endpoints send ----------------------------------------------------------------------

const rule = (priority: number) => ({ enabled: true, priority });
function settings(over: Partial<{ cents: number | null; version: number }> = {}): Config {
  return {
    dormant: { min_days_since_visit: 180, default_rebooking_days: 120 },
    types: {
      lapsed_high_value: { ...rule(1), spend_percentile_min: 80, spend_cents_min: over.cents ?? null },
      churned_member: { ...rule(2), membership_months: 6 },
      consult_not_converted: rule(3),
      overdue_maintenance: rule(4),
      one_and_done: { ...rule(5), min_days_since_visit: 90 },
      lapsed_regular: rule(5),
      unused_balance: rule(6),
    },
    revenue: { rate_low: 0.08, rate_high: 0.15 },
  } as unknown as Config;
}

const g = (key: string, label: string, patients: number | null, low: number | null, high: number | null, over: Partial<SummaryGroup> = {}): SummaryGroup => ({
  key, label, available: true, patients, kind: "new", lowCents: low, highCents: high, rateLow: 0.08, rateHigh: 0.15, rateSource: "assumed", ...over,
}); // prettier-ignore

const GROUPS: SummaryGroup[] = [
  g("lapsed_high_value", "Lapsed high-value", 40, 500_000, 900_000),
  g("churned_member", "Churned member", null, null, null, { available: false }),
  g("overdue_maintenance", "Overdue maintenance", 120, 100_000, 300_000),
  g("unused_balance", "Unused balance", 9, 640_000, 640_000, { kind: "retention" }),
  g("unclassified", "Unclassified", 243, null, null, { kind: null }),
];

function input(over: Partial<SummaryInput> = {}): SummaryInput {
  return {
    clinic: "Springfield Clinic",
    generatedOn: "2026-10-21",
    source: { kind: "saved", day: "2026-10-18" },
    dormant: 412,
    patients: 3000,
    lowCents: 600_000,
    highCents: 1_200_000,
    groups: GROUPS,
    settings: settings(),
    settingsVersion: 0,
    ...over,
  };
}

const WHEN = new Date("2026-10-21T12:00:00Z");
const textOf = (bytes: Uint8Array) => parsePdf(bytes).pages.map((p) => p.text.join("\n")).join("\n");
/** The same text with line breaks and wrapped lines joined, for sentences. */
const flatOf = (bytes: Uint8Array) => textOf(bytes).replace(/\s+/g, " ");

// --- the file ---------------------------------------------------------------------------------------------------------

test("the file is a valid PDF: header, objects at their offsets, trailer, US Letter, title", () => {
  const { raw, pages, objects } = parsePdf(buildSummaryPdf(input(), WHEN));
  assert.ok(pages.length >= 1);
  assert.match(objects.get(3)!, /Helvetica /);
  assert.match(raw, /\/MediaBox \[0 0 612 792\]/);
  assert.match(objects.get(5)!, /\/Title \(Dormant patients: summary report\)/);
  assert.match(objects.get(5)!, /\/CreationDate \(D:20261021120000Z\)/);
  assert.match(objects.get(1)!, /\/Lang \(en-US\)/);
});

test("the same input gives the same bytes", () => {
  assert.deepEqual(buildSummaryPdf(input(), WHEN), buildSummaryPdf(input(), WHEN));
});

test("every page carries the logo, the brand name, the privacy line, the footer text and Page i of n", () => {
  const many = Array.from({ length: 120 }, (_, i) => g(`k${i}`, `Group number ${i + 1}`, i, i * 1000, i * 2000));
  const { pages } = parsePdf(buildSummaryPdf(input({ groups: many }), WHEN));
  assert.ok(pages.length >= 4, `a long table runs onto several pages (got ${pages.length})`);
  pages.forEach((page, i) => {
    assert.ok(page.drawsLogo, `page ${i + 1} draws the logo`);
    assert.ok(page.text.includes(REPORT_BRAND_NAME), `page ${i + 1} has the brand name`);
    assert.ok(page.text.includes(REPORT_FOOTER_TEXT), `page ${i + 1} has the footer text`);
    assert.ok(page.text.join(" ").includes(REPORT_PRIVACY_LINE.slice(0, 40)), `page ${i + 1} has the privacy line`);
    assert.ok(page.text.includes(`Page ${i + 1} of ${pages.length}`), `page ${i + 1} says its number`);
  });
});

test("a long table repeats its header row and never splits a row or runs past the margins", () => {
  const many = Array.from({ length: 120 }, (_, i) => g(`k${i}`, `Group number ${i + 1}`, i, i * 1000, i * 2000));
  const { pages } = parsePdf(buildSummaryPdf(input({ groups: many }), WHEN));
  const withTable = pages.filter((p) => p.text.includes("Patient group"));
  assert.ok(withTable.length >= 3, "the header comes back on each page the table runs onto");
  for (const page of pages)
    for (const m of page.ops.matchAll(/ ([\d.]+) ([\d.]+) Td /g)) {
      const y = Number(m[2]);
      assert.ok(y > 20 && y < 780, `text at y=${y} is on the page`);
    }
  const names = pages.flatMap((p) => p.text.filter((t) => /^Group number \d+$/.test(t)));
  assert.equal(names.length, 120);
  assert.equal(new Set(names).size, 120);
});

test("body text stays between the header and the footer on every page", () => {
  const many = Array.from({ length: 120 }, (_, i) => g(`k${i}`, `Group ${i}`, i, 0, 100));
  const { pages } = parsePdf(buildSummaryPdf(input({ groups: many }), WHEN));
  for (const page of pages) {
    const ys = [...page.ops.matchAll(/BT \/F\d [\d.]+ Tf [\d. ]+ rg ([\d.]+) ([\d.]+) Td \(([^)]*)\)/g)]
      .filter((m) => !/Always-On|Page \d|PLACEHOLDER|Summary totals|has no patient|contact details|clinic owner/.test(m[3]!))
      .map((m) => Number(m[2]));
    for (const y of ys) assert.ok(y > 94 && y < 700, `body text at y=${y}`);
  }
});

// --- the figures --------------------------------------------------------------------------------------------------------

test("the headline and group figures are the ones the Overview formats", () => {
  const bytes = buildSummaryPdf(input(), WHEN);
  const text = textOf(bytes);
  const flat = flatOf(bytes);
  assert.match(text, new RegExp(`Dormant patients\\n${formatCount(412)}\\nof ${formatCount(3000)} patients`));
  assert.ok(text.includes(`Recoverable revenue\n${formatRange(600_000, 1_200_000)}`));
  assert.ok(text.includes(formatRange(500_000, 900_000)));
  assert.ok(text.includes(formatRange(100_000, 300_000)));
  assert.ok(text.includes(`${formatMoney(640_000)} already paid`));
  assert.ok(text.includes("Prepaid balance: not counted as new revenue"));
  assert.ok(text.includes("At an assumed return rate of 8% to 15%"));
  assert.ok(flat.includes("These patients don't fit any patient type, so there's no basis for an estimate."));
  assert.ok(text.includes("No membership records have been imported."), "a group without data says why, not a number");
  assert.ok(flat.includes("New revenue if some of them come back. Prepaid balances aren't included."));
});

test("the figures equal the xlsx report built from the same data", () => {
  const types = GROUPS.map((x) => ({
    type_key: x.key, label: x.label, description: "", kind: x.kind, available: x.available, patient_count: x.patients,
    revenue_low_cents: x.lowCents, revenue_high_cents: x.highCents, rate_low: x.rateLow, rate_high: x.rateHigh,
    rate_source: x.rateSource, top_service_name: null,
  })); // prettier-ignore
  const summary = { dormant_count: 412, patients_total: 3000, new_revenue_low_cents: 600_000, new_revenue_high_cents: 1_200_000 };
  const xlsx = reportSheets(
    reportFromSaved({
      clinic: "Springfield Clinic", timeZone: "UTC",
      latest: { finished_at: "2026-10-18T10:00:00Z", summary } as never, types: types as never, patients: [],
    }),
  )[0]!.rows; // prettier-ignore
  const cell = (c: unknown) => (c && typeof c === "object" && "v" in c ? (c as { v: unknown }).v : c);
  const find = (label: string) => xlsx.find((r) => cell(r[0]) === label)!.map(cell);
  const pdf = textOf(
    buildSummaryPdf(
      summaryFromSaved({
        clinic: "Springfield Clinic", today: "2026-10-21", timeZone: "UTC",
        data: { run_id: "r", finished_at: "2026-10-18T10:00:00Z", settings_version: 0, settings_source: "defaults", settings: settings() as never, summary, types: types as never } as SummaryOut,
      }),
      WHEN,
    ),
  ); // prettier-ignore
  assert.equal(find("Dormant patients")[1], 412);
  assert.ok(pdf.includes(formatCount(find("Dormant patients")[1] as number)));
  const lo = (find("Recoverable revenue, low")[1] as number) * 100;
  const hi = (find("Recoverable revenue, high")[1] as number) * 100;
  assert.ok(pdf.includes(formatRange(lo, hi)));
  for (const t of GROUPS.filter((x) => x.available && x.kind === "new" && x.lowCents !== null)) {
    const row = find(t.label);
    assert.equal(row[1], t.patients);
    assert.ok(pdf.includes(formatRange((row[2] as number) * 100, (row[3] as number) * 100)), t.label);
  }
});

test("a group's patients and the total row come from the same numbers", () => {
  const text = textOf(buildSummaryPdf(input(), WHEN));
  assert.match(text, /All groups\n412\n\$6,000 to \$12,000\nPrepaid balance isn't included\./);
});

// --- wording and privacy --------------------------------------------------------------------------------------------------

test("the wording is honest: estimates, a range, the clinic's own history, and none of the banned words", () => {
  const text = flatOf(buildSummaryPdf(input(), WHEN));
  assert.ok(text.includes(HOW_ESTIMATED.slice(0, 60)));
  assert.match(text, /estimates based on your clinic's own history, not forecasts/);
  assert.match(text, /Recoverable revenue/);
  for (const banned of [/\blost\b/i, /\bguarantee/i, /\bpromise/i, /\bwill (earn|recover|bring|make)\b/i, /\bexpect(ed)?\b/i])
    assert.doesNotMatch(text, banned);
  assert.doesNotMatch([HOW_ESTIMATED, FILE_NOTE, REPORT_PRIVACY_LINE].join(" "), /\blost\b|guarantee/i);
});

test("no patient names, contact details or file names get into the file", () => {
  const raw = Buffer.from(buildSummaryPdf(input({ source: { kind: "file" } }), WHEN)).toString("latin1");
  for (const secret of ["march-export.csv", "@example.test", "Zelda", "5550101"]) assert.ok(!raw.includes(secret));
  const fromFile = summaryFromFile({
    clinic: "C", today: "2026-10-21",
    data: { summary: {}, types: [], settings: settings(), settings_version: 0, patients: [{ display_name: "Zelda Canary", external_id: "P1" }] } as never,
  }); // prettier-ignore
  assert.deepEqual(Object.keys(fromFile).sort(), ["clinic", "dormant", "generatedOn", "groups", "highCents", "lowCents", "patients", "settings", "settingsVersion", "source"]);
});

test("a file report says so plainly and does not name the file; a saved one says which day", () => {
  const file = textOf(buildSummaryPdf(input({ source: { kind: "file" } }), WHEN));
  assert.match(file, /This report is from an imported file\./);
  assert.match(file, /not saved/);
  assert.match(file, /Return rates are assumed\./);
  const saved = textOf(buildSummaryPdf(input(), WHEN));
  assert.match(saved, /Source: your saved analysis from October 18, 2026\./);
  assert.doesNotMatch(saved, /imported file/);
});

// --- the settings used ------------------------------------------------------------------------------------------------------

test("the settings are printed, and the dollar cutoff only when it is set", () => {
  const without = textOf(buildSummaryPdf(input({ settingsVersion: 0 }), WHEN));
  assert.match(without, /The standard settings:/);
  assert.match(without, /Dormant after 180 days without a visit/);
  assert.match(without, /Usual time between visits: 120 days\./);
  assert.match(without, /the top 20% of patients by spend\./);
  assert.doesNotMatch(without, /anyone who has spent more than/);
  assert.match(without, /an assumed range of 8% to 15%/);

  const set = textOf(buildSummaryPdf(input({ settings: settings({ cents: 500_000 }), settingsVersion: 4 }), WHEN));
  assert.match(set, /Your saved settings \(version 4\):/);
  assert.match(set, /the top 20% of patients by spend, and anyone who has spent more than \$5,000 in total\./);
});

test("patient types that are switched off are listed", () => {
  const c = settings();
  c.types.lapsed_regular.enabled = false;
  c.types.one_and_done.enabled = false;
  assert.ok(settingsLines(c).includes("Patient types switched off: One-and-done, Lapsed regulars."));
  assert.ok(!settingsLines(settings()).some((l) => l.includes("switched off")));
});

// --- text handling -----------------------------------------------------------------------------------------------------------

test("text is measured from the real Helvetica widths", () => {
  assert.equal(textWidth("A", "regular", 1000), 667);
  assert.equal(textWidth("A", "bold", 1000), 722);
  assert.equal(textWidth(" ", "regular", 1000), 278);
  assert.equal(textWidth("é", "regular", 1000), textWidth("e", "regular", 1000));
});

test("letters with accents keep their accent, anything the font lacks becomes a question mark", () => {
  assert.equal(simplify("Café Ünïcode"), "Caf\xE9 \xDCn\xEFcode");
  assert.equal(simplify("5 – 6 ’s"), "5 \x96 6 \x92s");
  assert.equal(simplify("日本 ☃"), "?? ?");
  assert.equal(simplify("ő"), "o");
  const text = textOf(buildSummaryPdf(input({ clinic: "Café Ünïcode (Main) \\ 日本" }), WHEN));
  assert.ok(text.includes("Caf\xE9 \xDCn\xEFcode (Main) \\ ??"));
});

test("wrapping never produces a line wider than the box, and cuts a word that cannot fit", () => {
  const lines = wrap("a very long clinic name that must wrap onto more lines ".repeat(3) + "x".repeat(200), "regular", 10, 150);
  for (const l of lines) assert.ok(textWidth(l, "regular", 10) <= 150 + 0.001, l);
  assert.ok(lines.length > 4);
  assert.deepEqual(wrap("", "regular", 10, 100), [""]);
});

test("the file name follows the report's pattern", () => {
  assert.equal(summaryFileName("2026-10-21", "saved"), "dormant-patients-summary-2026-10-21-saved.pdf");
  assert.equal(summaryFileName("2026-10-21", "file"), "dormant-patients-summary-2026-10-21-from-file.pdf");
});

// --- the logo ----------------------------------------------------------------------------------------------------------------

test("the logo asset is an RGB PNG the writer can embed as it is", () => {
  const png = readPng(decodeBase64(REPORT_LOGO_PNG_BASE64));
  assert.ok(png.width > 0 && png.height > 0 && png.data.length > 100);
  const doc = new PdfDocument({ title: "t", creator: "c", created: WHEN, logo: png });
  doc.addPage().image(0, 0, 10, 10);
  const { objects } = parsePdf(doc.build());
  assert.match(objects.get(6)!, new RegExp(`/Width ${png.width} /Height ${png.height} /ColorSpace /DeviceRGB`));
  assert.match(objects.get(6)!, /\/Predictor 15 \/Colors 3/);
});

test("a logo with transparency or the wrong format is refused with a plain message", () => {
  const rgba = Uint8Array.from(decodeBase64(REPORT_LOGO_PNG_BASE64));
  rgba[25] = 6; // colour type RGBA
  assert.throws(() => readPng(rgba), /RGB PNG/);
  assert.throws(() => readPng(new Uint8Array(40)), /not a PNG/);
});

// --- outside tools, when present ----------------------------------------------------------------------------------------------

const has = (tool: string) => spawnSync("which", [tool]).status === 0;

test("pdftotext reads the same text on every page", { skip: !has("pdftotext") && "pdftotext is not installed" }, () => {
  const bytes = buildSummaryPdf(input({ settings: settings({ cents: 500_000 }), settingsVersion: 2 }), WHEN);
  const dir = mkdtempSync(join(tmpdir(), "summary-pdf-"));
  const file = join(dir, "report.pdf");
  writeFileSync(file, bytes);
  const out = execFileSync("pdftotext", ["-layout", file, "-"], { encoding: "utf8" });
  const { pages } = parsePdf(bytes);
  assert.equal(out.split("\f").filter((p) => p.trim()).length, pages.length);
  assert.ok(out.includes(formatRange(600_000, 1_200_000)));
  assert.equal(out.split(REPORT_FOOTER_TEXT).length - 1, pages.length);
  assert.ok(out.includes("Summary totals only."));
});

test("mutool opens the file, counts its pages and finds the logo on each", { skip: !has("mutool") && "mutool is not installed" }, () => {
  const many = Array.from({ length: 60 }, (_, i) => g(`k${i}`, `Group ${i + 1}`, i, 0, 100));
  const bytes = buildSummaryPdf(input({ groups: many }), WHEN);
  const dir = mkdtempSync(join(tmpdir(), "summary-pdf-"));
  const file = join(dir, "report.pdf");
  writeFileSync(file, bytes);
  const { pages } = parsePdf(bytes);
  const info = execFileSync("mutool", ["info", file], { encoding: "utf8" });
  assert.match(info, new RegExp(`Pages: ${pages.length}`));
  const trace = execFileSync("mutool", ["trace", file], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
  assert.equal((trace.match(/<fill_image /g) ?? []).length, pages.length, "the logo is drawn on every page");
  execFileSync("mutool", ["draw", "-o", join(dir, "p%d.png"), file]); // renders without error
});
