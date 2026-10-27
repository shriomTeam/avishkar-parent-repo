import test from "node:test";
import assert from "node:assert/strict";

import { clinicOf, initialsOf, personOf, roleLabel } from "../lib/profile.ts";

test("a clinic without a name is 'Your clinic' with the letter D", () => {
  assert.deepEqual(clinicOf("  Riverside Skin "), { name: "Riverside Skin", letter: "R" });
  for (const missing of ["", "   ", null, undefined]) assert.deepEqual(clinicOf(missing), { name: "Your clinic", letter: "D" });
});

test("the person is the name, else the email, else 'Signed in'", () => {
  assert.deepEqual(personOf({ display_name: "Maya Rao", email: "m@x.test" }), { name: "Maya Rao", initials: "MR" });
  assert.deepEqual(personOf({ display_name: " ", email: "maya@x.test" }), { name: "maya@x.test", initials: "M" });
  assert.deepEqual(personOf({ display_name: "", email: "" }), { name: "Signed in", initials: "SI" });
  assert.deepEqual(personOf(null), { name: "Signed in", initials: "SI" });
  assert.equal(initialsOf("a b c"), "AB");
});

test("a role reads in words, and a missing role is left out", () => {
  assert.equal(roleLabel("owner"), "owner");
  assert.equal(roleLabel("office_manager"), "office manager");
  for (const missing of ["", "  ", null, undefined]) assert.equal(roleLabel(missing), null);
});
