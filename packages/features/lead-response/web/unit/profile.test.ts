import test from "node:test";
import assert from "node:assert/strict";

import { clinicOf, personOf, roleLabel } from "../lib/profile.ts";

test("the clinic: its name and first letter, with a fallback", () => {
  assert.deepEqual(clinicOf("  Glow Aesthetics "), { name: "Glow Aesthetics", letter: "G" });
  assert.deepEqual(clinicOf(""), { name: "Your clinic", letter: "C" });
  assert.deepEqual(clinicOf(undefined), { name: "Your clinic", letter: "C" });
});

test("the person: name, else email, else 'Signed in'", () => {
  assert.deepEqual(personOf({ display_name: "Maya Rao", email: "m@x.com" }), { name: "Maya Rao", initials: "MR" });
  assert.deepEqual(personOf({ display_name: "", email: "maya@x.com" }), { name: "maya@x.com", initials: "M" });
  assert.deepEqual(personOf({ display_name: "Prince", email: "" }), { name: "Prince", initials: "P" });
  assert.deepEqual(personOf(null), { name: "Signed in", initials: "?" });
});

test("the role reads as words and is left out when missing", () => {
  assert.equal(roleLabel("office_manager"), "office manager");
  assert.equal(roleLabel("owner"), "owner");
  assert.equal(roleLabel(""), null);
  assert.equal(roleLabel(null), null);
});
