/**
 * The colour pairs the Dormant patients styles use, read from the stylesheet's own variables, checked against WCAG
 * 2.2 AA: 4.5:1 for text, 3:1 for the edge of a control, a focus ring and meaningful graphics. Run with
 * `node --test`; the measured ratios are printed so they can be reported.
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../styles/reactivation.css", import.meta.url), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  assert.ok(start >= 0, `${selector} block not found`);
  const body = css.slice(start, css.indexOf("\n}", start));
  const vars: Record<string, string> = {};
  for (const m of body.matchAll(/(--dp-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b/g)) vars[m[1]!] = m[2]!.toLowerCase();
  return vars;
}

const saved = block(".dp-scope");
// Inside the file frame the brand tokens are swapped for blue ones; everything else is inherited.
const file = { ...saved, ...block(".dp-file-frame") };
// The platform's own page background, behind the feature (apps/web globals.css).
const PAGE = "#fafaf9";

const channel = (v: number) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => channel(parseInt(hex.slice(i, i + 2), 16) / 255)) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

type Pair = { what: string; fg: string; bg: string; min: number };
const color = (vars: Record<string, string>, ref: string) => (ref.startsWith("#") ? ref : vars[ref]!);

function check(label: string, vars: Record<string, string>, pairs: [string, string, string, number][]) {
  test(label, () => {
    const rows: string[] = [];
    for (const [what, fg, bg, min] of pairs) {
      const a = color(vars, fg);
      const b = color(vars, bg);
      assert.ok(a && b, `${what}: unknown token`);
      const ratio = contrast(a, b);
      rows.push(`${ratio.toFixed(2).padStart(6)}  (needs ${min})  ${what}  ${a} on ${b}`);
      assert.ok(ratio >= min, `${what}: ${ratio.toFixed(2)} is below ${min} (${a} on ${b})`);
    }
    console.log(`\n${label}\n${rows.join("\n")}`);
  });
}

const TEXT = 4.5;
const UI = 3;

check("saved mode: text is 4.5:1 or better", saved, [
  ["body text on a card", "--dp-ink", "--dp-surface", TEXT],
  ["body text on the page", "--dp-ink", PAGE, TEXT],
  ["body text on a table header", "--dp-ink", "--dp-subtle", TEXT],
  ["body text on a hovered row", "--dp-ink", "--dp-accent-tint", TEXT],
  ["muted text on a card", "--dp-muted", "--dp-surface", TEXT],
  ["muted text on the page", "--dp-muted", PAGE, TEXT],
  ["muted text on a table header", "--dp-muted", "--dp-subtle", TEXT],
  ["muted text on a hovered row", "--dp-muted", "--dp-accent-tint", TEXT],
  ["muted text on soft lime", "--dp-muted", "--dp-accent-soft", TEXT],
  ["muted text on a sunk fill (neutral badge)", "--dp-muted", "--dp-sunk", TEXT],
  ["faint text on a card", "--dp-faint", "--dp-surface", TEXT],
  ["faint text on the page", "--dp-faint", PAGE, TEXT],
  ["text on the lime fill (button, lead tile)", "--dp-on-accent", "--dp-accent", TEXT],
  ["text on the lime fill, hovered", "--dp-on-accent", "--dp-accent-hover", TEXT],
  ["secondary text on the lime fill", "--dp-on-accent-muted", "--dp-accent", TEXT],
  ["dark green text on a card", "--dp-accent-ink", "--dp-surface", TEXT],
  ["dark green text on soft lime (badge, active)", "--dp-accent-ink", "--dp-accent-soft", TEXT],
  ["dark green text on a hovered row", "--dp-accent-ink", "--dp-accent-tint", TEXT],
  ["link text on a card", "--dp-link", "--dp-surface", TEXT],
  ["link text on the page", "--dp-link", PAGE, TEXT],
  ["link text on a table header", "--dp-link", "--dp-subtle", TEXT],
  ["success badge", "--dp-ok-ink", "--dp-ok-soft", TEXT],
  ["warning badge and notice", "--dp-warn-ink", "--dp-warn-soft", TEXT],
  ["warning text on a card (unavailable)", "--dp-warn-ink", "--dp-surface", TEXT],
  ["error badge and notice", "--dp-bad-ink", "--dp-bad-soft", TEXT],
  ["error text on a card", "--dp-bad-ink", "--dp-surface", TEXT],
  ["info notice and file badge", "--dp-info-ink", "--dp-info-soft", TEXT],
  ["muted text inside the file frame", "--dp-muted", "--dp-info-soft", TEXT],
  ["tooltip text", "#ffffff", "--dp-ink", TEXT],
]);

check("saved mode: control edges, focus rings and graphics are 3:1 or better", saved, [
  ["input, select, checkbox and secondary button edge on a card", "--dp-control", "--dp-surface", UI],
  ["control edge on the page", "--dp-control", PAGE, UI],
  ["control edge on a table header", "--dp-control", "--dp-subtle", UI],
  ["focus ring on a card", "--dp-focus", "--dp-surface", UI],
  ["focus ring on the page", "--dp-focus", PAGE, UI],
  ["focus ring on a table header", "--dp-focus", "--dp-subtle", UI],
  ["focus ring on soft lime", "--dp-focus", "--dp-accent-soft", UI],
  ["focus ring on a hovered row", "--dp-focus", "--dp-accent-tint", UI],
  ["lime button and tile outline on a card", "--dp-accent-edge", "--dp-surface", UI],
  ["lime button outline against the lime itself", "--dp-accent-edge", "--dp-accent", UI],
  ["range bar on a card", "--dp-bar", "--dp-surface", UI],
  ["range bar on its track", "--dp-bar", "--dp-sunk", UI],
  ["dark green underline of the active tab on the page", "--dp-accent-ink", PAGE, UI],
]);

check("file mode (blue frame): text is 4.5:1 or better", file, [
  ["body text on the frame", "--dp-ink", "--dp-info-soft", TEXT],
  ["text on the blue fill", "--dp-on-accent", "--dp-accent", TEXT],
  ["text on the blue fill, hovered", "--dp-on-accent", "--dp-accent-hover", TEXT],
  ["dark blue text on soft blue", "--dp-accent-ink", "--dp-accent-soft", TEXT],
  ["dark blue text on a hovered row", "--dp-accent-ink", "--dp-accent-tint", TEXT],
  ["dark blue text on a card", "--dp-accent-ink", "--dp-surface", TEXT],
  ["link text on a card", "--dp-link", "--dp-surface", TEXT],
  ["link text on the frame", "--dp-link", "--dp-info-soft", TEXT],
  ["link text on soft blue", "--dp-link", "--dp-accent-soft", TEXT],
]);

check("file mode (blue frame): edges, focus rings and graphics are 3:1 or better", file, [
  ["focus ring on a card", "--dp-focus", "--dp-surface", UI],
  ["focus ring on the frame", "--dp-focus", "--dp-info-soft", UI],
  ["focus ring on soft blue", "--dp-focus", "--dp-accent-soft", UI],
  ["blue outline on a card", "--dp-accent-edge", "--dp-surface", UI],
  ["blue outline on the frame", "--dp-info-edge", "--dp-info-soft", UI],
  ["blue range bar on its track", "--dp-bar", "--dp-sunk", UI],
  ["control edge on the frame", "--dp-control", "--dp-info-soft", UI],
]);

test("lime is only ever a fill: no text or outline token is the lime", () => {
  for (const [name, value] of Object.entries(saved)) {
    if (/ink|edge|link|focus|control|bar/.test(name)) assert.notEqual(value, saved["--dp-accent"], name);
  }
  assert.match(css, /--dp-accent:\s*#a1ff62/);
});
