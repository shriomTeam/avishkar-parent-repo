/**
 * The classes this page adds to the shared building blocks, and the colour pairs the page relies on.
 * The shared Input border (1.4:1) and focus ring (2:1) are too faint for AA, so this page uses its
 * own control and focus styles, and sets the shared ring's colour darker for everything inside `SCOPE`.
 * web/unit/contrast.test.ts measures PAIRS against the app's own tokens and fails on any hex used here or in a
 * component that is not listed. Candidates for packages/ui later: a high-contrast control, a switch, a notice banner.
 */

/** The page-wide wrapper class: makes the shared `focus-ring` utility draw a dark green ring. */
export const SCOPE = "[--color-focus:#2f6b10]";
export const FOCUS = "focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-[#2f6b10]";
export const CONTROL =
  "rounded-lg border border-[#6b6878] bg-white px-3 py-2.5 text-[15px] text-ink focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-[#2f6b10] aria-[invalid=true]:border-danger aria-[invalid=true]:border-2";
export const CHECK =
  "size-5 shrink-0 cursor-pointer accent-[#2f6b10] focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-[#2f6b10]";
export const LINK = "text-[#38691d] underline underline-offset-2 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-[#2f6b10]";

/** Foreground, background, minimum ratio. 4.5 for text, 3 for edges, rings and graphics. */
export type Pair = { what: string; fg: string; bg: string; min: number };
export const PAGE = "#fafaf9";
export const PAIRS: Pair[] = [
  { what: "body text on a panel", fg: "#201d1d", bg: "#ffffff", min: 4.5 },
  { what: "body text on the page", fg: "#201d1d", bg: PAGE, min: 4.5 },
  { what: "help text on a panel", fg: "#74717d", bg: "#ffffff", min: 4.5 },
  { what: "help text on the page", fg: "#74717d", bg: PAGE, min: 4.5 },
  { what: "field error text on a panel", fg: "#ae3049", bg: "#ffffff", min: 4.5 },
  { what: "alert text on its box", fg: "#ae3049", bg: "#ffedf0", min: 4.5 },
  { what: "unsaved-changes text on its bar", fg: "#9a5424", bg: "#fff0e5", min: 4.5 },
  { what: "saved notice text on its box", fg: "#315218", bg: "#edffe1", min: 4.5 },
  { what: "active menu item text", fg: "#315218", bg: "#edffe1", min: 4.5 },
  { what: "button text on the brand fill", fg: "#201d1d", bg: "#a1ff62", min: 4.5 },
  { what: "link text on a panel", fg: "#38691d", bg: "#ffffff", min: 4.5 },
  { what: "'Coming later' tag text", fg: "#201d1d", bg: "#f1f0f3", min: 4.5 },
  { what: "field edge on a panel", fg: "#6b6878", bg: "#ffffff", min: 3 },
  { what: "invalid field edge on a panel", fg: "#b3261e", bg: "#ffffff", min: 3 },
  { what: "focus ring on a panel", fg: "#2f6b10", bg: "#ffffff", min: 3 },
  { what: "focus ring on the page", fg: "#2f6b10", bg: PAGE, min: 3 },
  { what: "focus ring on the unsaved-changes bar", fg: "#2f6b10", bg: "#fff0e5", min: 3 },
  { what: "checkbox mark on a panel", fg: "#2f6b10", bg: "#ffffff", min: 3 },
];

/** The shared tokens (apps/web/app/globals.css) the pairs above stand for. The test checks each still has this value. */
export const TOKENS: Record<string, string> = {
  "--color-ink": "#201d1d",
  "--color-muted": "#74717d",
  "--color-danger": "#b3261e",
  "--color-danger-soft": "#ffedf0",
  "--color-danger-ink": "#ae3049",
  "--color-warn-soft": "#fff0e5",
  "--color-warn-ink": "#9a5424",
  "--color-brand": "#a1ff62",
  "--color-brand-soft": "#edffe1",
  "--color-brand-ink": "#315218",
  "--color-neutral-soft": "#f1f0f3",
};
