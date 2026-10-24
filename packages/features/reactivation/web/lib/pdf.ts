/**
 * A small PDF writer for the summary report, built in the browser with no library (as report.ts does for .xlsx).
 *
 * It writes US Letter pages in the standard Helvetica fonts, which every PDF reader has, so no font is embedded.
 * Page content is written as plain, uncompressed text operators so a test can read it back. One PNG (the logo) can be
 * embedded; its compressed data is copied into the file as it is. Text outside what Windows-1252 can show is simplified
 * (an accented letter loses its accent; anything else becomes "?").
 */
import { HELVETICA_BOLD_WIDTHS, HELVETICA_WIDTHS, WIN_ANSI_EXTRA } from "./pdf-widths";

export type Rgb = [number, number, number];
export type FontKey = "regular" | "bold";

export const PAGE = { width: 612, height: 792 } as const;
const FONT_RESOURCE: Record<FontKey, string> = { regular: "F1", bold: "F2" };
const FONT_BASE: Record<FontKey, string> = { regular: "Helvetica", bold: "Helvetica-Bold" };
const WIDTHS: Record<FontKey, readonly number[]> = { regular: HELVETICA_WIDTHS, bold: HELVETICA_BOLD_WIDTHS };

export const hex = (value: string): Rgb => {
  const n = parseInt(value.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};

// --- text ---------------------------------------------------------------------------------------------------------

function byteFor(ch: string, widths: readonly number[]): number | null {
  const cp = ch.codePointAt(0) as number;
  let byte: number | null = null;
  if ((cp >= 32 && cp <= 126) || (cp >= 160 && cp <= 255)) byte = cp;
  else if (WIN_ANSI_EXTRA[cp] !== undefined) byte = WIN_ANSI_EXTRA[cp] as number;
  if (byte !== null && (widths[byte - 32] ?? 0) > 0) return byte;
  const base = ch.normalize("NFD")[0] ?? "";
  return /^[A-Za-z]$/.test(base) ? base.charCodeAt(0) : null;
}

/** The text as the single-byte characters the file will hold: Latin-1 letters kept, everything else simplified. */
export function simplify(text: string): string {
  let out = "";
  for (const ch of text.replace(/[\r\n\t]+/g, " ")) {
    const byte = byteFor(ch, HELVETICA_WIDTHS);
    out += String.fromCharCode(byte ?? 63);
  }
  return out;
}

export function textWidth(text: string, font: FontKey, size: number): number {
  const widths = WIDTHS[font];
  let total = 0;
  for (const ch of simplify(text)) total += widths[ch.charCodeAt(0) - 32] ?? 556;
  return (total * size) / 1000;
}

/** Breaks text into lines no wider than `width`. A word wider than the line is cut. */
export function wrap(text: string, font: FontKey, size: number, width: number): string[] {
  const lines: string[] = [];
  for (const paragraph of text.split("\n")) {
    let line = "";
    for (const word of paragraph.split(/\s+/).filter(Boolean)) {
      const attempt = line ? `${line} ${word}` : word;
      if (textWidth(attempt, font, size) <= width) {
        line = attempt;
        continue;
      }
      if (line) lines.push(line);
      let rest = word;
      while (textWidth(rest, font, size) > width && rest.length > 1) {
        let cut = rest.length - 1;
        while (cut > 1 && textWidth(rest.slice(0, cut), font, size) > width) cut--;
        lines.push(rest.slice(0, cut));
        rest = rest.slice(cut);
      }
      line = rest;
    }
    lines.push(line);
  }
  return lines;
}

/** A PDF string literal. Every byte outside plain ASCII is written as an octal escape, so the file stays ASCII. */
export function pdfString(text: string): string {
  let out = "(";
  for (const ch of simplify(text)) {
    const code = ch.charCodeAt(0);
    if (ch === "(" || ch === ")" || ch === "\\") out += `\\${ch}`;
    else if (code < 32 || code > 126) out += `\\${code.toString(8).padStart(3, "0")}`;
    else out += ch;
  }
  return `${out})`;
}

const num = (n: number) => (Math.round(n * 100) / 100).toString();
const color = (c: Rgb) => c.map((v) => num(v)).join(" ");

// --- a page -------------------------------------------------------------------------------------------------------

export class Page {
  readonly ops: string[] = [];

  text(text: string, x: number, y: number, o: { font?: FontKey; size?: number; color?: Rgb } = {}) {
    const { font = "regular", size = 10, color: c = [0, 0, 0] } = o;
    this.ops.push(`BT /${FONT_RESOURCE[font]} ${num(size)} Tf ${color(c)} rg ${num(x)} ${num(y)} Td ${pdfString(text)} Tj ET`);
  }

  line(x1: number, y1: number, x2: number, y2: number, o: { color?: Rgb; width?: number } = {}) {
    const { color: c = [0, 0, 0], width = 0.5 } = o;
    this.ops.push(`${color(c)} RG ${num(width)} w ${num(x1)} ${num(y1)} m ${num(x2)} ${num(y2)} l S`);
  }

  rect(x: number, y: number, w: number, h: number, o: { fill?: Rgb; stroke?: Rgb; width?: number } = {}) {
    const parts: string[] = [];
    if (o.fill) parts.push(`${color(o.fill)} rg`);
    if (o.stroke) parts.push(`${color(o.stroke)} RG ${num(o.width ?? 0.5)} w`);
    const paint = o.fill && o.stroke ? "B" : o.fill ? "f" : "S";
    this.ops.push(`${parts.join(" ")} ${num(x)} ${num(y)} ${num(w)} ${num(h)} re ${paint}`.trim());
  }

  /** Draws the embedded logo. */
  image(x: number, y: number, w: number, h: number) {
    this.ops.push(`q ${num(w)} 0 0 ${num(h)} ${num(x)} ${num(y)} cm /Im1 Do Q`);
  }
}

// --- a PNG to embed -----------------------------------------------------------------------------------------------

export type PngImage = { width: number; height: number; data: Uint8Array };

export function decodeBase64(text: string): Uint8Array {
  const bin = atob(text);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/** The size and the joined compressed data of an RGB, 8-bit, not interlaced PNG without transparency. */
export function readPng(bytes: Uint8Array): PngImage {
  const sig = [137, 80, 78, 71, 13, 10, 26, 10];
  if (bytes.length < 33 || sig.some((b, i) => bytes[i] !== b)) throw new Error("The logo is not a PNG file.");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const width = view.getUint32(16);
  const height = view.getUint32(20);
  if (bytes[24] !== 8 || bytes[25] !== 2 || bytes[28] !== 0)
    throw new Error("The logo must be an RGB PNG, 8 bits per channel, not interlaced and without transparency.");
  const chunks: Uint8Array[] = [];
  for (let at = 8; at + 8 <= bytes.length; ) {
    const length = view.getUint32(at);
    const type = String.fromCharCode(bytes[at + 4]!, bytes[at + 5]!, bytes[at + 6]!, bytes[at + 7]!);
    if (type === "IDAT") chunks.push(bytes.subarray(at + 8, at + 8 + length));
    if (type === "IEND") break;
    at += 12 + length;
  }
  const data = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  let offset = 0;
  for (const c of chunks) {
    data.set(c, offset);
    offset += c.length;
  }
  if (!data.length) throw new Error("The logo has no image data.");
  return { width, height, data };
}

// --- the document -------------------------------------------------------------------------------------------------

export type DocumentOptions = {
  title: string;
  creator: string;
  created: Date;
  /** Shown to screen readers and search. */
  language?: string;
  logo?: PngImage;
};

const latin1 = (text: string) => {
  const out = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i++) out[i] = text.charCodeAt(i) & 255;
  return out;
};

function pdfDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `D:${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}Z`;
}

export class PdfDocument {
  readonly pages: Page[] = [];
  private readonly options: DocumentOptions;

  constructor(options: DocumentOptions) {
    this.options = options;
  }

  addPage(): Page {
    const page = new Page();
    this.pages.push(page);
    return page;
  }

  /** The file. `decorate` is called once per page with its number and the total, to draw headers and footers. */
  build(decorate?: (page: Page, index: number, total: number) => void): Uint8Array {
    const { logo } = this.options;
    if (decorate) this.pages.forEach((page, i) => decorate(page, i, this.pages.length));

    // Object numbers: 1 catalog, 2 page tree, 3 and 4 fonts, 5 info, 6 image (if any), then a page and its content each.
    const imageId = logo ? 6 : 0;
    const firstPage = logo ? 7 : 6;
    const pageId = (i: number) => firstPage + i * 2;
    const bodies: (string | Uint8Array[])[] = [];
    bodies[1] = `<< /Type /Catalog /Pages 2 0 R /Lang (${this.options.language ?? "en-US"}) >>`;
    bodies[2] = `<< /Type /Pages /Kids [${this.pages.map((_, i) => `${pageId(i)} 0 R`).join(" ")}] /Count ${this.pages.length} >>`;
    bodies[3] = `<< /Type /Font /Subtype /Type1 /BaseFont /${FONT_BASE.regular} /Encoding /WinAnsiEncoding >>`;
    bodies[4] = `<< /Type /Font /Subtype /Type1 /BaseFont /${FONT_BASE.bold} /Encoding /WinAnsiEncoding >>`;
    bodies[5] = `<< /Title ${pdfString(this.options.title)} /Creator ${pdfString(this.options.creator)} /Producer ${pdfString(this.options.creator)} /CreationDate (${pdfDate(this.options.created)}) >>`;
    if (logo)
      bodies[imageId] = [
        latin1(
          `<< /Type /XObject /Subtype /Image /Width ${logo.width} /Height ${logo.height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns ${logo.width} >> /Length ${logo.data.length} >>\nstream\n`,
        ),
        logo.data,
        latin1("\nendstream"),
      ];
    const resources = `/Resources << /Font << /F1 3 0 R /F2 4 0 R >>${logo ? " /XObject << /Im1 6 0 R >>" : ""} >>`;
    this.pages.forEach((page, i) => {
      const content = page.ops.join("\n");
      bodies[pageId(i)] = `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE.width} ${PAGE.height}] ${resources} /Contents ${pageId(i) + 1} 0 R >>`;
      bodies[pageId(i) + 1] = `<< /Length ${content.length} >>\nstream\n${content}\nendstream`;
    });

    const parts: Uint8Array[] = [latin1("%PDF-1.4\n%\xE2\xE3\xCF\xD3\n")];
    const offsets: number[] = [];
    let size = parts[0]!.length;
    const push = (bytes: Uint8Array) => {
      parts.push(bytes);
      size += bytes.length;
    };
    for (let id = 1; id < bodies.length; id++) {
      offsets[id] = size;
      push(latin1(`${id} 0 obj\n`));
      const body = bodies[id]!;
      if (typeof body === "string") push(latin1(body));
      else body.forEach(push);
      push(latin1("\nendobj\n"));
    }
    const xrefAt = size;
    const count = bodies.length;
    let xref = `xref\n0 ${count}\n0000000000 65535 f \n`;
    for (let id = 1; id < count; id++) xref += `${String(offsets[id]).padStart(10, "0")} 00000 n \n`;
    xref += `trailer\n<< /Size ${count} /Root 1 0 R /Info 5 0 R >>\nstartxref\n${xrefAt}\n%%EOF\n`;
    push(latin1(xref));

    const out = new Uint8Array(size);
    let at = 0;
    for (const p of parts) {
      out.set(p, at);
      at += p.length;
    }
    return out;
  }
}

// --- flowing text and tables onto pages ---------------------------------------------------------------------------

export type Span = { text: string; font?: FontKey; size?: number; color?: Rgb };
export type Cell = { lines: Span[]; align?: "left" | "right" };
export type Column = { width: number; align?: "left" | "right" };

export type Layout = { left: number; right: number; top: number; bottom: number };

/** Lays blocks down the page, starting a new page when the next block will not fit. */
export class Flow {
  page: Page;
  y: number;
  readonly layout: Layout;
  private readonly doc: PdfDocument;

  constructor(doc: PdfDocument, layout: Layout) {
    this.doc = doc;
    this.layout = layout;
    this.page = doc.addPage();
    this.y = layout.top;
  }

  get width() {
    return this.layout.right - this.layout.left;
  }

  newPage() {
    this.page = this.doc.addPage();
    this.y = this.layout.top;
  }

  /** Makes room for a block this tall; returns true when that started a new page. */
  need(height: number): boolean {
    if (this.y - height >= this.layout.bottom) return false;
    this.newPage();
    return true;
  }

  gap(height: number) {
    this.y -= height;
  }

  /** One block of wrapped text. It is kept together unless it is taller than a page. */
  paragraph(text: string, o: { font?: FontKey; size?: number; color?: Rgb; leading?: number; x?: number; width?: number } = {}) {
    const { font = "regular", size = 10, color: c = [0, 0, 0], leading = size * 1.35, x = this.layout.left } = o;
    const lines = wrap(text, font, size, o.width ?? this.layout.right - x);
    this.need(Math.min(lines.length * leading, this.layout.top - this.layout.bottom));
    for (const line of lines) {
      if (this.y - leading < this.layout.bottom) this.newPage();
      this.y -= leading;
      this.page.text(line, x, this.y + size * 0.28, { font, size, color: c });
    }
  }

  /** A box with a border and a tint, holding wrapped text. */
  box(text: string, o: { fill: Rgb; stroke: Rgb; font?: FontKey; size?: number; color?: Rgb; title?: string }) {
    const size = o.size ?? 9.5;
    const leading = size * 1.4;
    const pad = 9;
    const inner = this.width - pad * 2;
    const lines = wrap(text, "regular", size, inner);
    const height = pad * 2 + lines.length * leading + (o.title ? leading : 0);
    this.need(height);
    const top = this.y;
    this.page.rect(this.layout.left, top - height, this.width, height, { fill: o.fill, stroke: o.stroke, width: 0.75 });
    let y = top - pad;
    if (o.title) {
      y -= leading;
      this.page.text(o.title, this.layout.left + pad, y + size * 0.28, { font: "bold", size, color: o.color });
    }
    for (const line of lines) {
      y -= leading;
      this.page.text(line, this.layout.left + pad, y + size * 0.28, { size, color: o.color });
    }
    this.y = top - height;
  }

  /** A table. The header row repeats on every page the table runs onto. Rows are not split across pages. */
  table(
    columns: Column[],
    head: string[],
    rows: Cell[][],
    o: { headFill: Rgb; rule: Rgb; headColor?: Rgb; pad?: number } = { headFill: [0.95, 0.95, 0.95], rule: [0.8, 0.8, 0.8] },
  ) {
    const pad = o.pad ?? 5;
    const headSize = 9;
    const headHeight = headSize * 1.35 + pad * 2;
    const xs: number[] = [];
    let x = this.layout.left;
    for (const c of columns) {
      xs.push(x);
      x += c.width;
    }
    const drawHead = () => {
      this.page.rect(this.layout.left, this.y - headHeight, this.width, headHeight, { fill: o.headFill });
      head.forEach((label, i) => {
        const col = columns[i]!;
        const w = textWidth(label, "bold", headSize);
        const tx = col.align === "right" ? xs[i]! + col.width - pad - w : xs[i]! + pad;
        this.page.text(label, tx, this.y - pad - headSize * 0.95, { font: "bold", size: headSize, color: o.headColor });
      });
      this.y -= headHeight;
    };
    this.need(headHeight + 40);
    drawHead();
    for (const row of rows) {
      const wrapped = row.map((cell, i) =>
        cell.lines.flatMap((span) =>
          wrap(span.text, span.font ?? "regular", span.size ?? 9.5, columns[i]!.width - pad * 2).map((text) => ({ ...span, text })),
        ),
      );
      const height = pad * 2 + Math.max(...wrapped.map((lines) => lines.reduce((n, s) => n + (s.size ?? 9.5) * 1.35, 0)));
      if (this.need(height)) drawHead();
      let ty = this.y;
      wrapped.forEach((lines, i) => {
        const col = columns[i]!;
        let cy = ty - pad;
        for (const span of lines) {
          const size = span.size ?? 9.5;
          cy -= size * 1.35;
          const w = textWidth(span.text, span.font ?? "regular", size);
          const tx = col.align === "right" ? xs[i]! + col.width - pad - w : xs[i]! + pad;
          this.page.text(span.text, tx, cy + size * 0.28, { font: span.font, size, color: span.color });
        }
      });
      this.y -= height;
      this.page.line(this.layout.left, this.y, this.layout.right, this.y, { color: o.rule, width: 0.5 });
    }
  }
}
