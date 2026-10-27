import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

import { indexCsv, parseRecord, readRecords } from "../lib/csv-read.ts";

const dir = new URL("./fixtures/", import.meta.url);
const names = readdirSync(dir)
  .filter((f) => f.endsWith(".csv"))
  .map((f) => f.slice(0, -4))
  .sort();

// The expected rows and start lines are what the server's csv reader gives (tests/test_csv_viewer_fixtures.py).
for (const name of names) {
  test(`reads the ${name} file the way the server does`, () => {
    const bytes = new Uint8Array(readFileSync(new URL(`${name}.csv`, dir)));
    const expected = JSON.parse(readFileSync(new URL(`${name}.json`, dir), "utf8")) as {
      rows: string[][];
      lines: number[];
    };
    const index = indexCsv(bytes);
    assert.equal(index.count, expected.rows.length);
    assert.deepEqual(readRecords(bytes, index, 0, index.count), expected.rows);
    assert.deepEqual([...index.lines], expected.lines);
  });
}

test("a page of records can be read from the middle without reading the rest", () => {
  const bytes = new Uint8Array(readFileSync(new URL("plain.csv", dir)));
  const index = indexCsv(bytes);
  const page = readRecords(bytes, index, 5, 8);
  assert.equal(page.length, 3);
  assert.equal(page[0]![0], "P4"); // record 5 is the fifth data row, after the header
  assert.equal(index.lines[5], 6);
});

test("parseRecord stops at the end of the first record", () => {
  assert.deepEqual(parseRecord('a,"b,c",d\nnext,row'), ["a", "b,c", "d"]);
  assert.deepEqual(parseRecord('"x\r\ny",z\r\n'), ["x\r\ny", "z"]);
  assert.deepEqual(parseRecord(""), [""]);
});

test("any grid of nasty cells survives being written as CSV and read back", () => {
  const alphabet = ['a', 'b', ' ', ',', '"', "\n", "\r\n", "é", "☃", "1"];
  let seed = 7;
  const next = (n: number) => {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed % n;
  };
  const write = (cell: string) => (/[",\r\n]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell);
  for (let round = 0; round < 200; round++) {
    const width = 1 + next(5);
    const grid: string[][] = [];
    for (let r = 0; r < 1 + next(8); r++) {
      const row: string[] = [];
      for (let c = 0; c < width; c++) {
        let cell = "";
        for (let k = next(5); k > 0; k--) cell += alphabet[next(alphabet.length)];
        row.push(cell);
      }
      // a row of blank cells is skipped by design, so make sure one cell has something in it
      row[0] = "x" + (row[0] ?? "");
      grid.push(row);
    }
    const bytes = new TextEncoder().encode(grid.map((row) => row.map(write).join(",")).join("\n") + "\n");
    const index = indexCsv(bytes);
    assert.deepEqual(readRecords(bytes, index, 0, index.count), grid, `round ${round}`);
  }
});
