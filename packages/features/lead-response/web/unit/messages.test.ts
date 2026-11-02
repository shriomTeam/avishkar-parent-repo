import test from "node:test";
import assert from "node:assert/strict";

import {
  AI_ROWS,
  COMING_LATER,
  ackCounter,
  addMinutes,
  changedSettings,
  classifySave,
  clock12,
  daySummary,
  holdingExample,
  hoursExample,
  quietExample,
  savedMessage,
  SAVE_PROBLEMS,
  slaExample,
  statusLine,
} from "../lib/messages.ts";
import { formFromConfig } from "../lib/settings.ts";
import { defaults } from "./helpers.ts";

test("the message after a save is the wording Ayush approved", () => {
  assert.equal(savedMessage(3), "Saved (version 3). These settings take effect when lead response is switched on for your clinic.");
  assert.equal(savedMessage(1), "Saved (version 1). These settings take effect when lead response is switched on for your clinic.");
  assert.doesNotMatch(savedMessage(2), /new messages|from now on/);
});

test("the status line: version 0 is the standard settings", () => {
  assert.equal(statusLine(0), "Using the standard settings.");
  assert.equal(statusLine(4), "Using your saved settings (version 4).");
});

test("clock times are written in 12 hours", () => {
  assert.equal(clock12("00:00"), "12:00 am");
  assert.equal(clock12("00:05"), "12:05 am");
  assert.equal(clock12("09:30"), "9:30 am");
  assert.equal(clock12("12:00"), "12:00 pm");
  assert.equal(clock12("13:45"), "1:45 pm");
  assert.equal(clock12("23:59"), "11:59 pm");
  assert.equal(clock12(""), "");
  assert.equal(clock12("25:00"), "");
});

test("adding minutes wraps past midnight", () => {
  assert.equal(addMinutes("10:00", 15), "10:15");
  assert.equal(addMinutes("23:50", 20), "00:10");
  assert.equal(addMinutes("10:00", 240), "14:00");
});

test("the holding example is written from the number in the box", () => {
  assert.equal(
    holdingExample("15"),
    "A lead texts at 10:00 am and nobody has replied. At 10:15 am (after 15 minutes) they get a short holding message.",
  );
  assert.match(holdingExample("60"), /At 11:00 am \(after 60 minutes\)/);
});

test("an example is blank while the box is not a valid number", () => {
  for (const bad of ["", "abc", "4", "61", "1.5"]) assert.equal(holdingExample(bad), "", bad);
  for (const bad of ["", "abc", "9", "241"]) assert.equal(slaExample(bad, "owner"), "", bad);
});

test("the target example names who is told", () => {
  assert.equal(slaExample("30", "office_manager"), "If a lead texts at 10:00 am and nobody has replied by 10:30 am, the office manager is told.");
  assert.match(slaExample("90", "owner"), /by 11:30 am, the owner is told\.$/);
});

test("the character counter", () => {
  assert.equal(ackCounter(0), "0 of 320 characters");
  assert.equal(ackCounter(321), "321 of 320 characters");
});

test("a day is a list of ranges or Closed", () => {
  assert.equal(daySummary([]), "Closed");
  assert.equal(daySummary([{ start: "09:00", end: "12:00" }, { start: "13:00", end: "17:30" }]), "9:00 am to 12:00 pm, 1:00 pm to 5:30 pm");
});

test("the hours example counts open days", () => {
  const f = formFromConfig(defaults());
  assert.match(hoursExample(f.hours), /closed every day/);
  const one = { ...f.hours, mon: [{ start: "09:00", end: "10:00" }] };
  assert.equal(hoursExample(one), "Open 1 day a week.");
  assert.equal(hoursExample({ ...one, tue: [{ start: "09:00", end: "10:00" }] }), "Open 2 days a week.");
});

test("the quiet hours example names the clinic's time zone", () => {
  assert.equal(quietExample({ on: false, start: "21:00", end: "08:00" }, "America/Chicago"), "No quiet hours are set.");
  assert.equal(
    quietExample({ on: true, start: "21:00", end: "08:00" }, "America/Chicago"),
    "Quiet hours run from 9:00 pm to 8:00 am in your clinic's time zone (America/Chicago).",
  );
  assert.equal(quietExample({ on: true, start: "", end: "08:00" }, "UTC"), "");
});

test("what changed lists setting names only, in page order, never values", () => {
  const before = defaults();
  const after = defaults();
  after.ack_text = "A brand new sentence";
  after.sla_minutes = 90;
  after.quiet_hours = { start: "21:00", end: "07:00" };
  const names = changedSettings(before, after);
  assert.deepEqual(names, ["Instant reply wording", "Staff response target", "Quiet hours"]);
  assert.doesNotMatch(names.join(" "), /brand new|90|21:00/);
  assert.deepEqual(changedSettings(before, defaults()), []);
});

test("a failed save is told apart by status and by the 422's own code", () => {
  assert.equal(classifySave(412, "settings changed since you loaded them; reload and retry"), "stale");
  assert.equal(classifySave(403, "feature_access_denied"), "forbidden");
  assert.equal(classifySave(422, "invalid_request"), "invalid");
  assert.equal(classifySave(422, "ai_settings_not_available_yet"), "ai_not_available");
  assert.equal(classifySave(422, undefined), "invalid");
  assert.equal(classifySave(500, undefined), "failed");
  assert.equal(classifySave(0, undefined), "failed");
});

test("the conflict message is the approved sentence", () => {
  assert.equal(SAVE_PROBLEMS.stale.title, "Settings changed elsewhere. Reload.");
});

test("every problem has a title and a sentence that never blames the person", () => {
  for (const p of Object.values(SAVE_PROBLEMS)) {
    assert.ok(p.title.length > 0 && p.text.length > 0);
    assert.doesNotMatch(p.title + p.text, /invalid_request|error code|exception/i);
  }
});

test("the AI rows are plain labels with one tag, nothing that reads as working", () => {
  assert.equal(COMING_LATER, "Coming later");
  assert.equal(AI_ROWS.length, 7);
  assert.equal(new Set(AI_ROWS).size, AI_ROWS.length);
});
