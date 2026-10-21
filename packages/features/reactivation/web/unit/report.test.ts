import test from "node:test";
import assert from "node:assert/strict";

import {
  GROUP_HEADERS,
  SENSITIVE_NOTE,
  buildReport,
  crc32,
  dayIn,
  makeWorkbook,
  makeZip,
  reportFileName,
  reportSheets,
  sheetName,
  xmlText,
  type ReportInput,
  type ReportRow,
} from "../lib/report.ts";

const bytes = (s: string) => new TextEncoder().encode(s);

test("crc32 gives the standard check values", () => {
  assert.equal(crc32(new Uint8Array()), 0);
  assert.equal(crc32(bytes("123456789")), 0xcbf43926);
  assert.equal(crc32(bytes("The quick brown fox jumps over the lazy dog")), 0x414fa339);
  assert.equal(crc32(bytes("a")), 0xe8b7be43);
});

/** A minimal zip reader, written independently of makeZip, to check what it wrote. */
function readZip(zip: Uint8Array) {
  const view = new DataView(zip.buffer, zip.byteOffset, zip.byteLength);
  let eocd = zip.length - 22;
  assert.equal(view.getUint32(eocd, true), 0x06054b50, "end of central directory");
  const count = view.getUint16(eocd + 10, true);
  let at = view.getUint32(eocd + 16, true);
  const out: { name: string; data: Uint8Array; crc: number }[] = [];
  for (let i = 0; i < count; i++) {
    assert.equal(view.getUint32(at, true), 0x02014b50, "central entry");
    const method = view.getUint16(at + 10, true);
    const crc = view.getUint32(at + 16, true);
    const size = view.getUint32(at + 24, true);
    const nameLen = view.getUint16(at + 28, true);
    const local = view.getUint32(at + 42, true);
    const name = new TextDecoder().decode(zip.subarray(at + 46, at + 46 + nameLen));
    assert.equal(method, 0);
    assert.equal(view.getUint32(local, true), 0x04034b50, "local header");
    assert.equal(view.getUint16(local + 6, true) & 0x0800, 0x0800, "UTF-8 names");
    const localNameLen = view.getUint16(local + 26, true);
    const start = local + 30 + localNameLen;
    out.push({ name, data: zip.slice(start, start + size), crc });
    at += 46 + nameLen;
  }
  return out;
}

test("a zip holds the entries as written, with the right checksums and UTF-8 names", () => {
  const zip = makeZip(
    [
      { name: "a.txt", data: bytes("hello") },
      { name: "dir/é☃.xml", data: bytes("<x>wörld</x>") },
      { name: "empty", data: new Uint8Array() },
    ],
    new Date(2026, 9, 20, 13, 14, 16),
  );
  const entries = readZip(zip);
  assert.deepEqual(entries.map((e) => e.name), ["a.txt", "dir/é☃.xml", "empty"]);
  assert.equal(new TextDecoder().decode(entries[1]!.data), "<x>wörld</x>");
  for (const e of entries) assert.equal(crc32(e.data), e.crc, e.name);
  assert.equal(zip[0], 0x50); // "PK"
  assert.equal(zip[1], 0x4b);
});

test("xml text is escaped and stripped of what XML cannot hold", () => {
  assert.equal(xmlText(`a & b <c> "d"`), "a &amp; b &lt;c&gt; &quot;d&quot;");
  assert.equal(xmlText("a\u0000b\u0008c\u000Bd\u001Fe"), "abcde");
  assert.equal(xmlText("tab\tnew\nline\r"), "tab\tnew\nline\r");
  assert.equal(xmlText("ok \u{1F600} fine"), "ok \u{1F600} fine");
  assert.equal(xmlText("lone \uD800 surrogate"), "lone  surrogate");
});

test("sheet names follow Excel's rules and stay unique", () => {
  const used = new Set<string>(["summary"]);
  assert.equal(sheetName("Lapsed high-value", used), "Lapsed high-value");
  assert.equal(sheetName("a:b/c\\d?e*f[g]h", used), "a b c d e f g h");
  assert.equal(sheetName("x".repeat(50), used).length, 31);
  assert.equal(sheetName("Summary", used), "Summary 2"); // the summary sheet's name is taken
  assert.equal(sheetName("lapsed high-value", used), "lapsed high-value 2");
  assert.equal(sheetName("   ", used), "Sheet");
  assert.equal(sheetName("'quoted'", used), "quoted");
});

const row = (over: Partial<ReportRow> = {}): ReportRow => ({
  id: "abc",
  name: "Maya Rao",
  status: "dormant",
  usualService: "Botox",
  lastVisitDay: "2026-01-02",
  daysSince: 291,
  likelihood: "High",
  score: 70,
  basisCents: 25050,
  lowCents: 2004,
  highCents: 3758,
  offerService: "Facial",
  reasons: ["One visit", "No return"],
  ...over,
});

const input = (): ReportInput => ({
  clinic: "Riverside & Co",
  generatedOn: "2026-10-20",
  source: "Saved analysis from 2026-10-18",
  totals: { dormant: 3, patients: 10, lowCents: 5000, highCents: 9000 },
  types: [
    { key: "one_and_done", label: "One-and-done", description: "Visited once.", available: true, patients: 2, lowCents: 3000, highCents: 5000, topService: "Botox" },
    { key: "churned_member", label: "Churned member", description: "Left.", available: false, patients: null, lowCents: null, highCents: null, topService: null },
    { key: "unclassified", label: "Unclassified", description: "Matches none.", available: true, patients: 1, lowCents: null, highCents: null, topService: null },
    { key: "overdue_maintenance", label: "Overdue maintenance", description: "Overdue.", available: true, patients: 0, lowCents: 0, highCents: 0, topService: null },
  ],
  rows: new Map([
    ["one_and_done", [row(), row({ id: "def", name: "=SUM(1+1)" })]],
    ["unclassified", [row({ id: "ghi", name: "Zoë <Q> & \"R\"", lowCents: null, highCents: null })]],
  ]),
});

test("the report has a summary and a sheet for every type that has patients", () => {
  const sheets = reportSheets(input());
  assert.deepEqual(sheets.map((s) => s.name), ["Summary", "One-and-done", "Unclassified"]); // none for 0 patients or unavailable
  const summary = sheets[0]!.rows;
  assert.equal(summary[0]![0] && (summary[0]![0] as { v: string }).v, "Dormant patients report");
  const flat = summary.map((r) => r.map((c) => (c && typeof c === "object" ? c.v : c)));
  assert.deepEqual(flat[2], ["Clinic", "Riverside & Co"]);
  assert.deepEqual(flat[3], ["Report date", "2026-10-20"]);
  assert.deepEqual(flat[4], ["Source", "Saved analysis from 2026-10-18"]);
  assert.deepEqual(flat[5], ["Note", SENSITIVE_NOTE]);
  assert.deepEqual(flat[8], ["Dormant patients", 3]);
  assert.deepEqual(flat[9], ["Patients analysed", 10]);
  assert.deepEqual(flat[10], ["Recoverable revenue, low", 50]);
  assert.deepEqual(flat[11], ["Recoverable revenue, high", 90]);
  const groups = flat.slice(15);
  assert.deepEqual(groups[0], ["One-and-done", 2, 30, 50, "Botox", "One-and-done"]);
  assert.deepEqual(groups[1], ["Churned member", "Not available"]);
  assert.deepEqual(groups[2], ["Unclassified", 1, null, null, null, "Unclassified"]);
  assert.deepEqual(groups[3], ["Overdue maintenance", 0, 0, 0, null, null]);
});

test("a group sheet has its heading, a count, the column headings and one line per patient", () => {
  const [, one, unclassified] = reportSheets(input());
  const flat = one!.rows.map((r) => r.map((c) => (c && typeof c === "object" ? c.v : c)));
  assert.equal(flat[0]![0], "One-and-done");
  assert.equal(flat[1]![0], "Visited once.");
  assert.equal(flat[2]![0], "2 patients");
  assert.deepEqual(flat[4], GROUP_HEADERS);
  assert.equal(one!.freeze, 5);
  assert.equal(flat.length, 5 + 2);
  assert.deepEqual(flat[5], ["Maya Rao", "abc", "Dormant", "Botox", "2026-01-02", 291, "High", 70, 250.5, 20.04, 37.58, "Facial", "One visit; No return"]);
  assert.equal(flat[6]![0], "=SUM(1+1)"); // kept as text
  assert.equal(unclassified!.rows[2]![0] && (unclassified!.rows[2]![0] as { v: string }).v, "1 patient");
  const none = unclassified!.rows[5]!.map((c) => (c && typeof c === "object" ? c.v : c));
  assert.equal(none[9], null); // not sized: left empty
});

test("the workbook is a zip with the parts a spreadsheet program needs, and no formulas", () => {
  const file = buildReport(input(), new Date(2026, 9, 20));
  const parts = readZip(file);
  const names = parts.map((p) => p.name);
  for (const need of ["[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml"])
    assert.ok(names.includes(need), need);
  const text = (n: string) => new TextDecoder().decode(parts.find((p) => p.name === n)!.data);
  assert.match(text("xl/workbook.xml"), /<sheet name="One-and-done" sheetId="2" r:id="rId2"\/>/);
  const sheet2 = text("xl/worksheets/sheet2.xml");
  assert.match(sheet2, /<c r="A7" t="inlineStr"><is><t xml:space="preserve">=SUM\(1\+1\)<\/t><\/is><\/c>/); // a string, not a formula
  assert.doesNotMatch(sheet2, /<f>/);
  assert.match(text("xl/worksheets/sheet3.xml"), /Zoë &lt;Q&gt; &amp; &quot;R&quot;/);
  assert.match(sheet2, /<pane ySplit="5" topLeftCell="A6" activePane="bottomLeft" state="frozen"\/>/);
  for (const p of parts) assert.equal(crc32(p.data), p.crc, p.name);
  assert.throws(() => makeWorkbook([]));
});

test("the file name carries the day and where the figures came from, and nothing else", () => {
  assert.equal(reportFileName("2026-10-20", "saved"), "dormant-patients-report-2026-10-20-saved.xlsx");
  assert.equal(reportFileName("2026-10-20", "file"), "dormant-patients-report-2026-10-20-from-file.xlsx");
});

test("the day of an instant follows the clinic's time zone, from one formatter", () => {
  const instant = "2026-03-14T02:30:00Z";
  assert.equal(dayIn("America/New_York")(instant), "2026-03-13");
  assert.equal(dayIn("Asia/Tokyo")(instant), "2026-03-14");
  assert.equal(dayIn("UTC")("2026-12-31T23:59:59Z"), "2026-12-31");
  assert.equal(dayIn("Not/AZone")(instant), "2026-03-14"); // an unknown zone falls back to the UTC day
  assert.equal(dayIn("UTC")("not a date"), null);
  const day = dayIn("America/New_York");
  for (let i = 0; i < 1000; i++) assert.equal(day(instant), "2026-03-13"); // reusable for every patient
});
