/** The numbers in limits.json drive the form. Boundary values are built from them, so changing the file changes the test. */
import test from "node:test";
import assert from "node:assert/strict";

import limits from "../lib/limits.json" with { type: "json" };
import { formFromConfig, validate, type FormState } from "../lib/settings.ts";
import { defaults } from "./helpers.ts";

const form = (patch: Partial<FormState>): FormState => ({ ...formFromConfig(defaults()), ...patch });

for (const [name, key, other] of [
  ["holding", "holding_minutes", { sla: String(limits.sla_minutes.max) }],
  ["sla", "sla_minutes", { holding: String(limits.holding_minutes.min) }],
] as const) {
  const { min, max } = limits[key];
  const field = name as "holding" | "sla";
  test(`${name}: ${min} and ${max} are accepted, ${min - 1} and ${max + 1} are not`, () => {
    for (const v of [min, max]) assert.equal(validate(form({ ...other, [field]: String(v) }))[field], undefined, String(v));
    for (const v of [min - 1, max + 1]) assert.ok(validate(form({ ...other, [field]: String(v) }))[field], String(v));
  });
}

test("the range message names the limits", () => {
  assert.equal(validate(form({ holding: "4" })).holding, `Enter a number from ${limits.holding_minutes.min} to ${limits.holding_minutes.max}.`);
  assert.equal(validate(form({ sla: "9" })).sla, `Enter a number from ${limits.sla_minutes.min} to ${limits.sla_minutes.max}.`);
});

test("the message length limit counts characters, and the counter message names it", () => {
  const max = limits.ack_text.max_length;
  assert.equal(validate(form({ ack: "a".repeat(max) })).ack, undefined);
  assert.match(validate(form({ ack: "a".repeat(max + 1) })).ack!, new RegExp(`${max} characters or fewer. It is ${max + 1}`));
});

test("a day takes the number of ranges the limit says, no more", () => {
  const f = formFromConfig(defaults());
  const windows = Array.from({ length: limits.windows_per_day + 1 }, (_, i) => ({
    start: `${String(8 + i * 2).padStart(2, "0")}:00`,
    end: `${String(9 + i * 2).padStart(2, "0")}:00`,
  }));
  assert.equal(validate({ ...f, hours: { ...f.hours, mon: windows.slice(0, limits.windows_per_day) } }).hours, undefined);
  assert.match(validate({ ...f, hours: { ...f.hours, mon: windows } }).hours!.mon!, /at most 3/);
});

test("the days are the seven the server knows, in order, and the roles are the two it allows", () => {
  assert.deepEqual(limits.days, ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]);
  assert.deepEqual([...limits.escalation_roles].sort(), ["office_manager", "owner"]);
});
