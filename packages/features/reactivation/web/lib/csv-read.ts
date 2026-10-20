/**
 * Reads the file the user chose, in the browser, for the Imported file page. Nothing here touches the network.
 *
 * The file is kept as raw bytes. One pass over them records where each record starts (a byte offset and the line it
 * starts on), so a page of rows is decoded and split only when it is shown. Memory is the file plus about 8 bytes a
 * record, instead of millions of strings.
 *
 * The rules follow the server's reader (Python's csv module, in the importer's mode) so the page shows the same rows
 * the analysis used: RFC 4180 quoting, a quote opens a quoted field only at the start of a field, "" inside quotes is
 * a quote, line ends are \n, \r\n or \r (inside quotes too), a leading byte-order mark is dropped, and a record whose
 * cells are all blank is skipped. The line number of a record is the line it starts on, as in the import error list.
 * Unlike the server it never rejects: it only ever sees a file the server has already accepted.
 * Blank means ASCII whitespace only; a cell holding nothing but a non-ASCII space still counts as content here.
 */

export type CsvIndex = {
  /** Records found, header included. */
  count: number;
  /** Byte offset where each record starts. */
  starts: Uint32Array;
  /** The line each record starts on, counting from 1. */
  lines: Uint32Array;
};

const QUOTE = 34;
const COMMA = 44;
const LF = 10;
const CR = 13;

const isSpace = (c: number) => c === 32 || (c >= 9 && c <= 13) || (c >= 0x1c && c <= 0x1f);

// the reader's states, as plain numbers so the file runs under Node's built-in TypeScript support too
const StartField = 0;
const InField = 1;
const InQuoted = 2;
const QuoteInQuoted = 3;

/** One pass over the bytes. Records that are blank in every cell are left out, as the server leaves them out. */
export function indexCsv(bytes: Uint8Array): CsvIndex {
  let capacity = 1 << 12;
  let starts = new Uint32Array(capacity);
  let lines = new Uint32Array(capacity);
  let count = 0;
  const n = bytes.length;
  let i = n >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf ? 3 : 0;
  let recordStart = i;
  let recordLine = 1;
  let line = 1;
  let any = false;
  let state = StartField as number;

  const finish = () => {
    if (!any) return;
    if (count === capacity) {
      capacity *= 2;
      const s = new Uint32Array(capacity);
      s.set(starts);
      starts = s;
      const l = new Uint32Array(capacity);
      l.set(lines);
      lines = l;
    }
    starts[count] = recordStart;
    lines[count] = recordLine;
    count++;
  };

  for (; i < n; i++) {
    const c = bytes[i] as number;
    if (c === LF || c === CR) {
      if (state === InQuoted) {
        // a line end inside quotes belongs to the cell; it still counts as a line
        if (c === CR && bytes[i + 1] === LF) i++;
        line++;
        continue;
      }
      finish();
      if (c === CR && bytes[i + 1] === LF) i++;
      line++;
      recordStart = i + 1;
      recordLine = line;
      any = false;
      state = StartField;
      continue;
    }
    switch (state) {
      case StartField:
        if (c === QUOTE) state = InQuoted;
        else if (c === COMMA) state = StartField;
        else {
          state = InField;
          if (!isSpace(c)) any = true;
        }
        break;
      case InField:
        if (c === COMMA) state = StartField;
        else if (!isSpace(c)) any = true;
        break;
      case InQuoted:
        if (c === QUOTE) state = QuoteInQuoted;
        else if (!isSpace(c)) any = true;
        break;
      case QuoteInQuoted:
        if (c === QUOTE) {
          any = true; // "" is a quote character
          state = InQuoted;
        } else if (c === COMMA) state = StartField;
        else {
          state = InField;
          if (!isSpace(c)) any = true;
        }
        break;
    }
  }
  finish();
  return { count, starts: starts.slice(0, count), lines: lines.slice(0, count) };
}

/** The cells of the first record in the text, which holds one record and whatever follows it. */
export function parseRecord(text: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let state = StartField as number;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i] as string;
    if (ch === "\n" || ch === "\r") {
      if (state !== InQuoted) break;
      cell += ch;
      continue;
    }
    switch (state) {
      case StartField:
        if (ch === '"') state = InQuoted;
        else if (ch === ",") {
          cells.push(cell);
          cell = "";
        } else {
          cell += ch;
          state = InField;
        }
        break;
      case InField:
        if (ch === ",") {
          cells.push(cell);
          cell = "";
          state = StartField;
        } else cell += ch;
        break;
      case InQuoted:
        if (ch === '"') state = QuoteInQuoted;
        else cell += ch;
        break;
      case QuoteInQuoted:
        if (ch === '"') {
          cell += '"';
          state = InQuoted;
        } else if (ch === ",") {
          cells.push(cell);
          cell = "";
          state = StartField;
        } else {
          cell += ch;
          state = InField;
        }
        break;
    }
  }
  cells.push(cell);
  return cells;
}

const decoder = new TextDecoder("utf-8");

/** Record number `at` (0 is the header) as cells. */
export function readRecord(bytes: Uint8Array, index: CsvIndex, at: number): string[] {
  const start = index.starts[at] as number;
  const end = at + 1 < index.count ? (index.starts[at + 1] as number) : bytes.length;
  return parseRecord(decoder.decode(bytes.subarray(start, end)));
}

/** A page of records, from `from` up to but not including `to`. */
export function readRecords(bytes: Uint8Array, index: CsvIndex, from: number, to: number): string[][] {
  const out: string[][] = [];
  for (let at = from; at < Math.min(to, index.count); at++) out.push(readRecord(bytes, index, at));
  return out;
}

const cache = new WeakMap<ArrayBuffer, CsvIndex>();

/** The index for a buffer, built once however often the page is opened. */
export function indexFor(buffer: ArrayBuffer): CsvIndex {
  let index = cache.get(buffer);
  if (!index) {
    index = indexCsv(new Uint8Array(buffer));
    cache.set(buffer, index);
  }
  return index;
}
