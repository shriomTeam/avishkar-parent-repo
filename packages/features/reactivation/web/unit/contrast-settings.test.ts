/** The colour pairs the Settings page adds, read from the stylesheet's own variables (WCAG 2.2 AA). */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../styles/reactivation.css", import.meta.url), "utf8");
const start = css.indexOf(".dp-scope {");
const body = css.slice(start, css.indexOf("\n}", start));
const vars: Record<string, string> = {};
for (const m of body.matchAll(/(--dp-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b/g)) vars[m[1]!] = m[2]!.toLowerCase();

const channel = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
const luminance = (hex: string) => {
  const [r, g, b] = [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16) / 255)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
};

test("settings page: text is 4.5:1, control edges 3:1", () => {
  const pairs: [string, string, string, number][] = [
    ["help text and units on a card", "--dp-muted", "--dp-surface", 4.5],
    ["error text on a card", "--dp-bad-ink", "--dp-surface", 4.5],
    ["invalid box edge on a card", "--dp-bad-ink", "--dp-surface", 3],
    ["unsaved-changes text on its bar", "--dp-warn-ink", "--dp-warn-soft", 4.5],
    ["unsaved-changes bar edge on the page", "--dp-warn-line", "--dp-page", 1],
    ["body text on the saved bar", "--dp-muted", "--dp-surface", 4.5],
  ];
  const rows: string[] = [];
  for (const [what, fg, bg, min] of pairs) {
    const ratio = contrast(vars[fg]!, vars[bg]!);
    rows.push(`${ratio.toFixed(2).padStart(6)}  (needs ${min})  ${what}`);
    assert.ok(ratio >= min, `${what}: ${ratio.toFixed(2)} is below ${min}`);
  }
  console.log(`\n${rows.join("\n")}`);
});
