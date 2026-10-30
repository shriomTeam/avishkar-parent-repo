/**
 * The colours the settings page uses, measured (WCAG 2.2 AA: 4.5:1 for text, 3:1 for field edges, focus rings and
 * graphics). The pairs live in lib/look.ts. This test also reads the app's own stylesheet (it does not import it) so a
 * changed token fails here, and it fails on any colour written into a component that no pair covers.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

import { PAGE, PAIRS, TOKENS } from "../lib/look.ts";

const globals = readFileSync(new URL("../../../../../apps/web/app/globals.css", import.meta.url), "utf8");

const channel = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const luminance = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16) / 255)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

test("the contrast function agrees with known values", () => {
  assert.equal(contrast("#000000", "#ffffff").toFixed(2), "21.00");
  assert.equal(contrast("#777777", "#ffffff").toFixed(2), "4.48");
});

test("every colour pair the page uses is at least AA", () => {
  const rows: string[] = [];
  for (const p of PAIRS) {
    const ratio = contrast(p.fg, p.bg);
    rows.push(`${ratio.toFixed(2).padStart(6)}  (needs ${p.min})  ${p.what}`);
    assert.ok(ratio >= p.min, `${p.what}: ${ratio.toFixed(2)} is below ${p.min}`);
  }
  console.log(`\n${rows.join("\n")}`);
});

test("the shared tokens still have the values the pairs were measured with", () => {
  for (const [name, hex] of Object.entries(TOKENS)) {
    const found = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(globals);
    assert.ok(found, `${name} is not defined in globals.css`);
    assert.equal(found![1]!.toLowerCase(), hex, name);
  }
  const body = /body\s*{[^}]*background:\s*(#[0-9a-fA-F]{6})/.exec(globals);
  assert.equal(body?.[1]?.toLowerCase(), PAGE, "the page background changed");
});

test("no colour is written into a component without a pair that covers it", () => {
  const covered = new Set(PAIRS.flatMap((p) => [p.fg, p.bg]));
  const dir = new URL("../components/", import.meta.url);
  const files = [
    ...readdirSync(dir).map((f) => [f, readFileSync(new URL(f, dir), "utf8")] as const),
    ["lib/look.ts", readFileSync(new URL("../lib/look.ts", import.meta.url), "utf8")] as const,
  ];
  // Skeleton placeholders and the page background are decorative or measured above.
  const decorative = new Set([PAGE]);
  for (const [name, source] of files) {
    for (const hex of source.matchAll(/#[0-9a-fA-F]{6}\b/g)) {
      const value = hex[0].toLowerCase();
      assert.ok(covered.has(value) || decorative.has(value), `${name} uses ${value}, which no contrast pair covers`);
    }
  }
});

test("the shared focus ring is replaced where it is too faint", () => {
  assert.ok(contrast("#80cc4e", "#ffffff") < 3, "if the shared ring became strong enough, the page-wide override is no longer needed");
});
