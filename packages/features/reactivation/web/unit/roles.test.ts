import test from "node:test";
import assert from "node:assert/strict";

import { canRunRole } from "../lib/roles.ts";

test("only the owner and the office manager can import or run", () => {
  assert.equal(canRunRole("owner"), true);
  assert.equal(canRunRole("office_manager"), true);
  for (const role of ["front_desk", "provider", "consultant", "", null, undefined])
    assert.equal(canRunRole(role), false, String(role));
});
