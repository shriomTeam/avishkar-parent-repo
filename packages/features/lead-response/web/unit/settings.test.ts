import test from "node:test";
import assert from "node:assert/strict";

import {
  applyForm,
  charCount,
  errorList,
  formFromConfig,
  isStandard,
  parseWhole,
  QUIET_SUGGESTION,
  sameForm,
  validate,
} from "../lib/settings.ts";
import { defaults } from "./helpers.ts";

const base = () => formFromConfig(defaults());

test("the standard settings make a form with no errors", () => {
  assert.deepEqual(validate(base()), {});
  assert.equal(base().holding, "15");
  assert.equal(base().sla, "30");
  assert.equal(base().role, "office_manager");
  assert.equal(base().quiet.on, false);
});

test("whole numbers: blank is null, letters and decimals are not numbers", () => {
  assert.equal(parseWhole(""), null);
  assert.equal(parseWhole("  "), null);
  assert.equal(parseWhole(" 15 "), 15);
  for (const bad of ["1.5", "-3", "1e2", "ten", "1,5"]) assert.ok(Number.isNaN(parseWhole(bad)!), bad);
});

test("characters are counted as the server counts them", () => {
  assert.equal(charCount("abc"), 3);
  assert.equal(charCount("\u{1F600}\u{1F600}"), 2);
});

test("each number box says what is wrong in plain words", () => {
  assert.equal(validate({ ...base(), holding: "" }).holding, "Enter a number.");
  assert.equal(validate({ ...base(), holding: "abc" }).holding, "Use a whole number, with no letters or decimals.");
  assert.equal(validate({ ...base(), sla: "500" }).sla, "Enter a number from 10 to 240.");
});

test("the staff target must be longer than the holding time, and the message says by how much to look", () => {
  const e = validate({ ...base(), holding: "30", sla: "30" });
  assert.equal(e.sla, "The staff response target must be longer than the holding message time (30 minutes).");
  assert.equal(e.holding, undefined);
});

test("that comparison waits until both boxes are valid numbers", () => {
  assert.equal(validate({ ...base(), holding: "x", sla: "30" }).sla, undefined);
  assert.equal(validate({ ...base(), holding: "20", sla: "x" }).sla, "Use a whole number, with no letters or decimals.");
});

test("the instant reply: each problem has its own sentence", () => {
  assert.equal(validate({ ...base(), ack: "   " }).ack, "Write the message a new lead receives.");
  assert.match(validate({ ...base(), ack: "a".repeat(321) }).ack!, /^Shorten this to 320 characters or fewer\. It is 321\.$/);
  assert.match(validate({ ...base(), ack: "Hi {name}" }).ack!, /curly brackets/);
  assert.match(validate({ ...base(), ack: "Hi\tthere" }).ack!, /plain text/);
  assert.equal(validate({ ...base(), ack: "Line one\nLine two" }).ack, undefined);
});

test("business hours: one sentence per day, only for the days that are wrong", () => {
  const f = base();
  const e = validate({
    ...f,
    hours: {
      ...f.hours,
      mon: [{ start: "09:00", end: "10:00" }, { start: "09:30", end: "11:00" }],
      tue: [{ start: "10:00", end: "09:00" }],
      wed: [{ start: "", end: "09:00" }],
      thu: [{ start: "09:00", end: "10:00" }],
    },
  });
  assert.match(e.hours!.mon!, /overlap/);
  assert.match(e.hours!.tue!, /end after it starts/);
  assert.match(e.hours!.wed!, /start and an end time/);
  assert.equal(e.hours!.thu, undefined);
  assert.deepEqual(Object.keys(e.hours!).sort(), ["mon", "tue", "wed"]);
});

test("quiet hours: needs two different times only while switched on", () => {
  assert.equal(validate({ ...base(), quiet: { on: false, start: "10:00", end: "10:00" } }).quiet, undefined);
  assert.equal(validate({ ...base(), quiet: { on: true, start: "10:00", end: "10:00" } }).quiet, "The start and end times must be different.");
  assert.equal(validate({ ...base(), quiet: { on: true, start: "", end: "10:00" } }).quiet, "Set a start and an end time.");
});

test("the role must be one of the two the server allows", () => {
  assert.equal(validate({ ...base(), role: "owner" }).role, undefined);
  assert.equal(validate({ ...base(), role: "front_desk" }).role, "Choose who is told.");
});

test("the error list follows the page order and names the field to focus", () => {
  const f = base();
  const list = errorList(
    validate({ ...f, quiet: { on: true, start: "1:00", end: "2:00" }, sla: "1", holding: "1", ack: "", hours: { ...f.hours, tue: [{ start: "10:00", end: "09:00" }] } }),
  );
  assert.deepEqual(list.map((x) => x.id), ["field-ack", "field-holding", "field-sla", "field-hours-tue", "field-quiet"]);
  assert.ok(list.every((x) => x.label && x.message));
});

test("what is sent keeps the AI settings exactly as saved and trims and sorts what the form shows", () => {
  const saved = defaults();
  saved.ai_active_mode = "after_hours";
  const f = base();
  const body = applyForm(saved, {
    ...f,
    ack: "  Hello  ",
    holding: " 20 ",
    sla: "45",
    role: "owner",
    hours: { ...f.hours, mon: [{ start: "13:00", end: "17:00" }, { start: "08:00", end: "12:00" }] },
    quiet: { on: true, start: "22:00", end: "07:00" },
  });
  assert.equal(body.ack_text, "Hello");
  assert.equal(body.holding_minutes, 20);
  assert.equal(body.sla_minutes, 45);
  assert.equal(body.escalation_role, "owner");
  assert.deepEqual(body.business_hours.mon, [{ start: "08:00", end: "12:00" }, { start: "13:00", end: "17:00" }]);
  assert.deepEqual(body.quiet_hours, { start: "22:00", end: "07:00" });
  assert.equal(body.ai_enabled, false);
  assert.equal(body.ai_active_mode, "after_hours");
  assert.equal(body.send_mode, "draft");
  assert.deepEqual(saved.business_hours.mon, [], "the saved config is not changed in place");
});

test("switching quiet hours off sends null, on sends the two times", () => {
  assert.equal(applyForm(defaults(), base()).quiet_hours, null);
  assert.deepEqual(applyForm(defaults(), { ...base(), quiet: { on: true, ...QUIET_SUGGESTION } }).quiet_hours, QUIET_SUGGESTION);
});

test("a form made from a config and sent back is the same config", () => {
  const saved = defaults();
  saved.quiet_hours = { start: "20:00", end: "06:00" };
  saved.business_hours.fri = [{ start: "09:00", end: "12:00" }, { start: "13:00", end: "17:00" }];
  assert.deepEqual(applyForm(saved, formFromConfig(saved)), saved);
});

test("unsaved changes: any box, any window, the quiet switch", () => {
  const a = base();
  assert.equal(sameForm(a, base()), true);
  assert.equal(sameForm(a, { ...a, ack: a.ack + "!" }), false);
  assert.equal(sameForm(a, { ...a, holding: "16" }), false);
  assert.equal(sameForm(a, { ...a, sla: "31" }), false);
  assert.equal(sameForm(a, { ...a, role: "owner" }), false);
  assert.equal(sameForm(a, { ...a, hours: { ...a.hours, sat: [{ start: "09:00", end: "10:00" }] } }), false);
  assert.equal(sameForm(a, { ...a, quiet: { ...a.quiet, on: true } }), false);
  assert.equal(sameForm(a, { ...a, quiet: { ...a.quiet, start: "23:00" } }), true, "times of a switched-off quiet window do not count");
});

test("a changed window is a change, even with the same number of windows", () => {
  const a = { ...base(), hours: { ...base().hours, mon: [{ start: "09:00", end: "10:00" }] } };
  assert.equal(sameForm(a, { ...a, hours: { ...a.hours, mon: [{ start: "09:00", end: "10:30" }] } }), false);
});

test("reset: the standard values are what the server calls defaults", () => {
  const d = defaults();
  d.holding_minutes = 20;
  d.sla_minutes = 50;
  assert.equal(isStandard(formFromConfig(d), d), true);
  assert.equal(isStandard({ ...formFromConfig(d), sla: "51" }, d), false);
  assert.equal(isStandard(base(), defaults()), true);
});
