import test from "node:test";
import assert from "node:assert/strict";

import {
  formatAbout,
  formatCount,
  formatDay,
  formatDaysAgo,
  formatMoney,
  formatOverdue,
  formatPercent,
  formatRange,
  formatRateRange,
  rateBasisText,
  relativeTime,
} from "../lib/format.ts";

test("money is whole dollars with a thousands separator", () => {
  assert.equal(formatMoney(0), "$0");
  assert.equal(formatMoney(123_456), "$1,235");
  assert.equal(formatMoney(100_000_000), "$1,000,000");
  assert.equal(formatCount(12_345), "12,345");
});

test("ranges collapse when both ends are the same", () => {
  assert.equal(formatRange(1_300_000, 2_500_000), "$13,000 to $25,000");
  assert.equal(formatRange(500, 500), "$5");
  assert.equal(formatAbout(34_000, 64_000), "About $340 to $640");
  assert.equal(formatAbout(7_000, 7_000), "About $70");
});

test("rates and the plain-words basis", () => {
  assert.equal(formatPercent(0.08), "8%");
  assert.equal(formatRateRange(0.08, 0.15), "8% to 15%");
  assert.equal(formatRateRange(0.1, 0.1), "10%");
  assert.equal(rateBasisText("assumed", 0.08, 0.15), "At an assumed return rate of 8% to 15%");
  assert.equal(rateBasisText("measured", 0.12, 0.2), "At your measured return rate of 12% to 20%, from past campaigns");
  assert.equal(rateBasisText(null, 0.08, 0.15), "At an assumed return rate of 8% to 15%");
});

test("dates are the clinic's calendar day and are never shifted", () => {
  assert.equal(formatDay("2026-03-14"), "Mar 14, 2026");
  assert.equal(formatDay("2026-01-01"), "Jan 1, 2026");
  assert.equal(formatDay("not a day"), "not a day");
});

test("how long ago, and how overdue", () => {
  assert.equal(formatDaysAgo(0), "today");
  assert.equal(formatDaysAgo(-3), "today");
  assert.equal(formatDaysAgo(1), "1 day ago");
  assert.equal(formatDaysAgo(412), "412 days ago");
  assert.equal(formatDaysAgo(1_200), "1,200 days ago");
  assert.equal(formatOverdue(2.4), "2.4× their usual gap");
  assert.equal(formatOverdue(1.04), "1.0× their usual gap");
  assert.equal(formatOverdue(12), "12.0× their usual gap");
});

test("relative time still reads naturally", () => {
  const now = new Date("2026-10-18T12:00:00Z");
  assert.equal(relativeTime("2026-10-18T11:59:30Z", now), "just now");
  assert.equal(relativeTime("2026-10-18T09:00:00Z", now), "3 hours ago");
  assert.equal(relativeTime("2026-10-17T12:00:00Z", now), "yesterday");
});
