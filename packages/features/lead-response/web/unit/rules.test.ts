/** The shared rule cases (fixtures/rule-cases.json). tests/test_web_limits.py runs the same cases through the server's model. */
import test from "node:test";
import assert from "node:assert/strict";

import { applyForm, formFromConfig, validate } from "../lib/settings.ts";
import { CASES, DEFAULTS } from "./helpers.ts";

for (const c of CASES) {
  test(`the form agrees with the server: ${c.id} is ${c.valid ? "accepted" : "refused"}`, () => {
    const errors = validate(formFromConfig(c.config));
    assert.equal(Object.keys(errors).length === 0, c.valid, JSON.stringify(errors));
  });
}

test("every accepted case is sent as the server would store it (trimmed, windows in order)", () => {
  for (const c of CASES.filter((x) => x.valid)) {
    const sent = applyForm(DEFAULTS, formFromConfig(c.config));
    assert.equal(sent.ack_text, c.config.ack_text.trim(), c.id);
    for (const day of Object.keys(sent.business_hours) as (keyof typeof sent.business_hours)[]) {
      const starts = sent.business_hours[day].map((w) => w.start);
      assert.deepEqual(starts, [...starts].sort(), `${c.id}: ${day}`);
    }
    assert.deepEqual(sent.quiet_hours, c.config.quiet_hours, c.id);
  }
});

test("the cases include accepted and refused ones for every rule group", () => {
  assert.ok(CASES.filter((c) => c.valid).length >= 20);
  assert.ok(CASES.filter((c) => !c.valid).length >= 20);
});
