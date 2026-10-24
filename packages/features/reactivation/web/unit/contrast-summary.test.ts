/** The text colours of the summary report PDF against the fills they sit on (WCAG 2.2 AA, 4.5:1 for text). */
import test from "node:test";
import assert from "node:assert/strict";

import { PDF_COLORS } from "../lib/summary-pdf.ts";

type Rgb = [number, number, number];
const channel = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const luminance = ([r, g, b]: Rgb) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
const contrast = (a: Rgb, b: Rgb) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};
const WHITE: Rgb = [1, 1, 1];

test("the PDF's text is 4.5:1 or better on white and on its fills", () => {
  const { INK, MUTED, HEAD_FILL, TILE_FILL, INFO_FILL, INFO_INK } = PDF_COLORS;
  const pairs: [string, Rgb, Rgb][] = [
    ["body text on white", INK, WHITE],
    ["secondary text on white", MUTED, WHITE],
    ["table head text on its fill", INK, HEAD_FILL],
    ["tile label and hint on the tile", MUTED, TILE_FILL],
    ["tile figure on the tile", INK, TILE_FILL],
    ["file note on its box", INFO_INK, INFO_FILL],
  ];
  const rows: string[] = [];
  for (const [what, fg, bg] of pairs) {
    const ratio = contrast(fg, bg);
    rows.push(`${ratio.toFixed(2).padStart(6)}  ${what}`);
    assert.ok(ratio >= 4.5, `${what}: ${ratio.toFixed(2)}`);
  }
  console.log(`\n${rows.join("\n")}`);
});
