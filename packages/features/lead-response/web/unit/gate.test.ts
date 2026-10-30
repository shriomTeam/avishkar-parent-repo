import test from "node:test";
import assert from "node:assert/strict";

import { classifyGate } from "../lib/gate.ts";
import { canEditSettings } from "../lib/roles.ts";

test("a successful read opens the page", () => {
  assert.equal(classifyGate(200, undefined), "ok");
});

test("only the plain 'feature not enabled' answer is a 404", () => {
  assert.equal(classifyGate(403, "Feature 'lead_response' is not enabled"), "not_found");
  assert.equal(classifyGate(403, "Feature 'reactivation' is not enabled"), "not_found");
});

test("a role refusal shows the role view, not a 404", () => {
  assert.equal(classifyGate(403, "feature_access_denied"), "role");
  assert.equal(classifyGate(403, "Not allowed for your role"), "role");
});

test("anything else is an error the person can retry, never a 404", () => {
  for (const [status, detail] of [
    [401, "Not authenticated"],
    [403, "workspace_access_denied"],
    [403, undefined],
    [404, "Not Found"],
    [500, undefined],
    [502, undefined],
    [503, "service_unavailable"],
    [0, undefined],
  ] as const)
    assert.equal(classifyGate(status, detail), "error", `${status} ${detail}`);
});

test("only the owner and office manager are shown the editable form", () => {
  assert.equal(canEditSettings("owner"), true);
  assert.equal(canEditSettings("office_manager"), true);
  for (const r of ["front_desk", "consultant", "provider", "", null, undefined]) assert.equal(canEditSettings(r), false, String(r));
});
