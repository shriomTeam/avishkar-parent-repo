import test from "node:test";
import assert from "node:assert/strict";

import { formatSavedAt } from "../lib/messages.ts";
import { saveOutcome } from "../lib/save.ts";
import { defaults } from "./helpers.ts";

test("a new version says what changed by name and when it applies", () => {
  const before = { version: 2, config: defaults() };
  const after = { version: 3, config: { ...defaults(), sla_minutes: 60, ack_text: "A different sentence entirely" } };
  const o = saveOutcome(before, after);
  assert.equal(o.kind, "saved");
  assert.equal(o.text, "Saved (version 3). These settings take effect when lead response is switched on for your clinic.");
  assert.deepEqual(o.changed, ["Instant reply wording", "Staff response target"]);
  assert.doesNotMatch(JSON.stringify(o), /different sentence|60/);
});

test("the first save from the standard settings is version 1", () => {
  const o = saveOutcome({ version: 0, config: defaults() }, { version: 1, config: { ...defaults(), holding_minutes: 20 } });
  assert.equal(o.text, "Saved (version 1). These settings take effect when lead response is switched on for your clinic.");
  assert.deepEqual(o.changed, ["Holding message time"]);
});

test("the same version back means nothing was written", () => {
  const o = saveOutcome({ version: 2, config: defaults() }, { version: 2, config: defaults() });
  assert.equal(o.kind, "unchanged");
  assert.deepEqual(o.changed, []);
  assert.match(o.text, /Nothing to save/);
});

test("the saved time is written in the clinic's own time zone", () => {
  assert.equal(formatSavedAt("2026-10-30T19:05:00Z", "America/Chicago"), "Oct 30, 2026, 2:05 PM");
  assert.equal(formatSavedAt("2026-10-30T19:05:00Z", "Asia/Kolkata"), "Oct 31, 2026, 12:35 AM");
});

test("a missing or odd time gives nothing, and a bad zone falls back to UTC", () => {
  assert.equal(formatSavedAt(null, "UTC"), "");
  assert.equal(formatSavedAt("not a date", "UTC"), "");
  assert.equal(formatSavedAt("2026-10-30T19:05:00Z", "Not/AZone"), "Oct 30, 2026, 7:05 PM");
});
