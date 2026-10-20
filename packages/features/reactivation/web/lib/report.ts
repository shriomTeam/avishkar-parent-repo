/**
 * The Dormant patients report as an .xlsx file, built in the browser with no library.
 *
 * An .xlsx file is a zip of a few XML parts. This writes them directly: a stored (uncompressed) zip, text cells only
 * (never formulas, so nothing in a patient's name can run in a spreadsheet), and a handful of styles. It is one file,
 * with no imports, so the browser build and Node's test runner both load it as it is.
 *
 * The data is whatever the screen already shows: saved results from the report endpoint, or file results from
 * browser memory. Nothing here talks to the network or stores anything.
 */

// --- CRC-32 ---------------------------------------------------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ (bytes[i] as number)) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// --- a zip with stored entries --------------------------------------------------------------------------------------

export type ZipEntry = { name: string; data: Uint8Array };

const encoder = new TextEncoder();

/** A zip file holding the entries uncompressed. Names are UTF-8. Throws if the archive would need zip64. */
export function makeZip(entries: ZipEntry[], when: Date = new Date()): Uint8Array {
  if (entries.length > 0xfffe) throw new Error("too many files for a zip");
  const year = Math.max(1980, when.getFullYear());
  const dosTime = (when.getHours() << 11) | (when.getMinutes() << 5) | (when.getSeconds() >> 1);
  const dosDate = ((year - 1980) << 9) | ((when.getMonth() + 1) << 5) | when.getDate();
  const names = entries.map((e) => encoder.encode(e.name));
  let size = 22;
  entries.forEach((e, i) => {
    size += 30 + (names[i] as Uint8Array).length + e.data.length + 46 + (names[i] as Uint8Array).length;
  });
  if (size > 0xfffffff0) throw new Error("the report is too large for a zip");
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  let at = 0;
  const offsets: number[] = [];
  const crcs: number[] = [];
  entries.forEach((e, i) => {
    const name = names[i] as Uint8Array;
    const crc = crc32(e.data);
    crcs.push(crc);
    offsets.push(at);
    view.setUint32(at, 0x04034b50, true);
    view.setUint16(at + 4, 20, true); // version needed
    view.setUint16(at + 6, 0x0800, true); // names are UTF-8
    view.setUint16(at + 8, 0, true); // stored
    view.setUint16(at + 10, dosTime, true);
    view.setUint16(at + 12, dosDate, true);
    view.setUint32(at + 14, crc, true);
    view.setUint32(at + 18, e.data.length, true);
    view.setUint32(at + 22, e.data.length, true);
    view.setUint16(at + 26, name.length, true);
    view.setUint16(at + 28, 0, true);
    out.set(name, at + 30);
    out.set(e.data, at + 30 + name.length);
    at += 30 + name.length + e.data.length;
  });
  const centralStart = at;
  entries.forEach((e, i) => {
    const name = names[i] as Uint8Array;
    view.setUint32(at, 0x02014b50, true);
    view.setUint16(at + 4, 20, true); // made by
    view.setUint16(at + 6, 20, true); // version needed
    view.setUint16(at + 8, 0x0800, true);
    view.setUint16(at + 10, 0, true);
    view.setUint16(at + 12, dosTime, true);
    view.setUint16(at + 14, dosDate, true);
    view.setUint32(at + 16, crcs[i] as number, true);
    view.setUint32(at + 20, e.data.length, true);
    view.setUint32(at + 24, e.data.length, true);
    view.setUint16(at + 28, name.length, true);
    view.setUint16(at + 30, 0, true); // extra
    view.setUint16(at + 32, 0, true); // comment
    view.setUint16(at + 34, 0, true); // disk
    view.setUint16(at + 36, 0, true); // internal attributes
    view.setUint32(at + 38, 0, true); // external attributes
    view.setUint32(at + 42, offsets[i] as number, true);
    out.set(name, at + 46);
    at += 46 + name.length;
  });
  view.setUint32(at, 0x06054b50, true);
  view.setUint16(at + 4, 0, true);
  view.setUint16(at + 6, 0, true);
  view.setUint16(at + 8, entries.length, true);
  view.setUint16(at + 10, entries.length, true);
  view.setUint32(at + 12, at - centralStart, true);
  view.setUint32(at + 16, centralStart, true);
  view.setUint16(at + 20, 0, true);
  return out;
}

// --- a workbook ------------------------------------------------------------------------------------------------------

export type Style = "title" | "bold" | "head" | "money" | "wrap" | "note";
export type Cell = string | number | null | { v: string | number | null; style: Style };
export type Sheet = {
  name: string;
  rows: Cell[][];
  /** Column widths in characters, by column. */
  widths?: number[];
  /** Rows kept in view above the data when scrolling. */
  freeze?: number;
};

const STYLE_INDEX: Record<Style, number> = { title: 1, bold: 2, head: 3, money: 4, wrap: 5, note: 6 };

// XML 1.0 allows tab, newline and carriage return among the control characters, and no lone surrogates.
// eslint-disable-next-line no-control-regex
const ILLEGAL_XML = /[\u0000-\u0008\u000B\u000C\u000E-\u001F￾￿]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/g;

export function xmlText(text: string): string {
  return text
    .replace(ILLEGAL_XML, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function columnName(index: number): string {
  let n = index + 1;
  let name = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    name = String.fromCharCode(65 + r) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

/** A sheet name Excel accepts: at most 31 characters, none of : \ / ? * [ ], not empty, and not already used. */
export function sheetName(label: string, used: Set<string>): string {
  let base = label.replace(/[:\\/?*[\]]/g, " ").replace(/^'+|'+$/g, "").replace(/\s+/g, " ").trim().slice(0, 31).trim();
  if (!base) base = "Sheet";
  let name = base;
  for (let n = 2; used.has(name.toLowerCase()); n++) {
    const suffix = ` ${n}`;
    name = base.slice(0, 31 - suffix.length).trimEnd() + suffix;
  }
  used.add(name.toLowerCase());
  return name;
}

function sheetXml(sheet: Sheet): string {
  const parts: string[] = [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
  ];
  if (sheet.freeze) {
    parts.push(
      `<sheetViews><sheetView workbookViewId="0"><pane ySplit="${sheet.freeze}" topLeftCell="A${sheet.freeze + 1}" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>`,
    );
  }
  if (sheet.widths?.length) {
    parts.push("<cols>");
    sheet.widths.forEach((w, i) => parts.push(`<col min="${i + 1}" max="${i + 1}" width="${w}" customWidth="1"/>`));
    parts.push("</cols>");
  }
  parts.push("<sheetData>");
  sheet.rows.forEach((row, r) => {
    const cells: string[] = [];
    row.forEach((cell, c) => {
      if (cell === null) return;
      const value = typeof cell === "object" ? cell.v : cell;
      if (value === null) return;
      const style = typeof cell === "object" ? ` s="${STYLE_INDEX[cell.style]}"` : "";
      const ref = `${columnName(c)}${r + 1}`;
      if (typeof value === "number") {
        if (Number.isFinite(value)) cells.push(`<c r="${ref}"${style}><v>${value}</v></c>`);
      } else {
        cells.push(`<c r="${ref}"${style} t="inlineStr"><is><t xml:space="preserve">${xmlText(value)}</t></is></c>`);
      }
    });
    parts.push(`<row r="${r + 1}">${cells.join("")}</row>`);
  });
  parts.push("</sheetData></worksheet>");
  return parts.join("");
}

const STYLES_XML =
  '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
  '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
  '<numFmts count="1"><numFmt numFmtId="164" formatCode="&quot;$&quot;#,##0.00"/></numFmts>' +
  '<fonts count="4">' +
  '<font><sz val="11"/><name val="Calibri"/></font>' +
  '<font><b/><sz val="16"/><name val="Calibri"/></font>' +
  '<font><b/><sz val="11"/><name val="Calibri"/></font>' +
  '<font><i/><sz val="11"/><color rgb="FF595959"/><name val="Calibri"/></font>' +
  "</fonts>" +
  '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>' +
  '<fill><patternFill patternType="solid"><fgColor rgb="FFEDEDED"/><bgColor indexed="64"/></patternFill></fill></fills>' +
  '<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>' +
  '<border><left/><right/><top/><bottom style="thin"><color rgb="FF808080"/></bottom><diagonal/></border></borders>' +
  '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
  '<cellXfs count="7">' +
  '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>' +
  '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>' +
  '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>' +
  '<xf numFmtId="0" fontId="2" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>' +
  '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>' +
  '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>' +
  '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>' +
  "</cellXfs>" +
  '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
  "</styleSheet>";

/** The bytes of an .xlsx workbook holding the sheets, in order. */
export function makeWorkbook(sheets: Sheet[], when: Date = new Date()): Uint8Array {
  if (sheets.length === 0) throw new Error("a workbook needs a sheet");
  const used = new Set<string>();
  const names = sheets.map((s) => sheetName(s.name, used));
  const text = (s: string) => encoder.encode(s);
  const head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
  const entries: ZipEntry[] = [
    {
      name: "[Content_Types].xml",
      data: text(
        head +
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
          '<Default Extension="xml" ContentType="application/xml"/>' +
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
          sheets
            .map(
              (_, i) =>
                `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`,
            )
            .join("") +
          "</Types>",
      ),
    },
    {
      name: "_rels/.rels",
      data: text(
        head +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
          "</Relationships>",
      ),
    },
    {
      name: "xl/workbook.xml",
      data: text(
        head +
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">' +
          "<sheets>" +
          names.map((n, i) => `<sheet name="${xmlText(n)}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join("") +
          "</sheets></workbook>",
      ),
    },
    {
      name: "xl/_rels/workbook.xml.rels",
      data: text(
        head +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          sheets
            .map(
              (_, i) =>
                `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`,
            )
            .join("") +
          `<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>` +
          "</Relationships>",
      ),
    },
    { name: "xl/styles.xml", data: text(STYLES_XML) },
    ...sheets.map((s, i) => ({ name: `xl/worksheets/sheet${i + 1}.xml`, data: text(sheetXml(s)) })),
  ];
  return makeZip(entries, when);
}

// --- the report --------------------------------------------------------------------------------------------------------

export type ReportRow = {
  id: string;
  name: string;
  status: string;
  usualService: string | null;
  lastVisitDay: string | null;
  daysSince: number | null;
  likelihood: string; // High, Medium, Low or ""
  score: number | null;
  basisCents: number;
  lowCents: number | null;
  highCents: number | null;
  offerService: string | null;
  reasons: string[];
};

export type ReportType = {
  key: string;
  label: string;
  description: string;
  available: boolean;
  patients: number | null;
  lowCents: number | null;
  highCents: number | null;
  topService: string | null;
};

export type ReportInput = {
  clinic: string;
  /** The day the report was made, "2026-10-20", in the clinic's time zone. */
  generatedOn: string;
  /** What the figures come from, in words: "Saved analysis from 2026-10-18" or "File march.csv, not saved". */
  source: string;
  totals: { dormant: number | null; patients: number | null; lowCents: number | null; highCents: number | null };
  /** In the order the Overview shows them. */
  types: ReportType[];
  /** Dormant patients by type key; a patient with no type is under "unclassified". */
  rows: Map<string, ReportRow[]>;
};

export const SENSITIVE_NOTE =
  "This file contains patient names. Share it only with people who need it, store it securely and delete it when you are done.";

export const GROUP_HEADERS = [
  "Patient",
  "Patient id",
  "Status",
  "Usual service",
  "Last visit",
  "Days since last visit",
  "Likelihood to come back",
  "Likelihood score",
  "Spend basis",
  "About value, low",
  "About value, high",
  "Recommended service",
  "Why",
];

const dollars = (cents: number | null): Cell => (cents === null ? null : { v: cents / 100, style: "money" });
const head = (text: string): Cell => ({ v: text, style: "head" });

/**
 * The calendar day of an instant in a time zone, as "2026-03-14". The formatter is made once per report: making one
 * per patient, as the patient list's own helper does for a page of 25, cost seconds and hundreds of MB of native
 * memory at 25,000 patients.
 */
export function dayIn(timeZone: string): (iso: string) => string | null {
  let format: Intl.DateTimeFormat | null = null;
  try {
    format = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" });
  } catch {
    format = null; // an unknown time zone: fall back to the UTC day
  }
  return (iso) => {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return null;
    return format ? format.format(d) : d.toISOString().slice(0, 10);
  };
}

export function reportFileName(day: string, mode: "saved" | "file"): string {
  return `dormant-patients-report-${day}-${mode === "saved" ? "saved" : "from-file"}.xlsx`;
}

/** The sheets of the report: a summary, then one sheet for every patient type that has patients. */
export function reportSheets(input: ReportInput): Sheet[] {
  const used = new Set<string>(["summary"]);
  const sheetOf = new Map<string, string>();
  const groups = input.types.filter((t) => (input.rows.get(t.key)?.length ?? 0) > 0);
  for (const t of groups) sheetOf.set(t.key, sheetName(t.label, used));

  const summary: Cell[][] = [
    [{ v: "Dormant patients report", style: "title" }],
    [],
    [{ v: "Clinic", style: "bold" }, input.clinic],
    [{ v: "Report date", style: "bold" }, input.generatedOn],
    [{ v: "Source", style: "bold" }, input.source],
    [{ v: "Note", style: "bold" }, { v: SENSITIVE_NOTE, style: "note" }],
    [],
    [{ v: "Totals", style: "bold" }],
    ["Dormant patients", input.totals.dormant],
    ["Patients analysed", input.totals.patients],
    ["Recoverable revenue, low", dollars(input.totals.lowCents)],
    ["Recoverable revenue, high", dollars(input.totals.highCents)],
    [],
    [{ v: "Patient groups", style: "bold" }],
    [head("Group"), head("Patients"), head("Could be worth, low"), head("Could be worth, high"), head("Top service"), head("Sheet")],
  ];
  for (const t of input.types) {
    summary.push(
      t.available
        ? [t.label, t.patients, dollars(t.lowCents), dollars(t.highCents), t.topService, sheetOf.get(t.key) ?? null]
        : [t.label, "Not available"],
    );
  }

  const sheets: Sheet[] = [{ name: "Summary", rows: summary, widths: [28, 70, 22, 22, 24, 28] }];
  for (const t of groups) {
    const rows = input.rows.get(t.key) ?? [];
    const lines: Cell[][] = [
      [{ v: t.label, style: "title" }],
      [{ v: t.description, style: "note" }],
      [{ v: `${rows.length} ${rows.length === 1 ? "patient" : "patients"}`, style: "bold" }],
      [],
      GROUP_HEADERS.map(head),
    ];
    for (const r of rows) {
      lines.push([
        r.name,
        r.id,
        r.status === "dormant" ? "Dormant" : r.status,
        r.usualService,
        r.lastVisitDay,
        r.daysSince,
        r.likelihood || null,
        r.score,
        dollars(r.basisCents),
        dollars(r.lowCents),
        dollars(r.highCents),
        r.offerService,
        r.reasons.join("; ") || null,
      ]);
    }
    sheets.push({
      name: sheetOf.get(t.key) as string,
      rows: lines,
      widths: [26, 38, 11, 24, 12, 12, 14, 10, 13, 14, 14, 24, 70],
      freeze: 5,
    });
  }
  return sheets;
}

export function buildReport(input: ReportInput, when: Date = new Date()): Uint8Array {
  return makeWorkbook(reportSheets(input), when);
}
