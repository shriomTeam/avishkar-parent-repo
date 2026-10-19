import test from "node:test";
import assert from "node:assert/strict";

import { DATA_NAV, NAV, activeHref, breadcrumb } from "../components/shell-nav.ts";

test("the sidebar has the three sections, in order", () => {
  assert.deepEqual(
    NAV.map((n) => n.label),
    ["Overview", "Runs", "Settings"],
  );
});

test("the active item follows the path, and type pages belong to the Overview", () => {
  assert.equal(activeHref("/reactivation"), "/reactivation");
  assert.equal(activeHref("/reactivation/types/one_and_done"), "/reactivation");
  assert.equal(activeHref("/reactivation/runs"), "/reactivation/runs");
  assert.equal(activeHref("/reactivation/settings"), "/reactivation/settings");
  assert.equal(activeHref("/reactivation/runs/abc"), "/reactivation/runs");
  assert.equal(activeHref("/elsewhere"), null);
});

test("the breadcrumb names the section, and the patient group on a type page", () => {
  assert.deepEqual(breadcrumb("/reactivation"), ["Workspace", "Overview"]);
  assert.deepEqual(breadcrumb("/reactivation/runs"), ["Workspace", "Runs"]);
  assert.deepEqual(breadcrumb("/reactivation/types/unclassified"), ["Workspace", "Overview", "Patient group"]);
});

test("Import data is its own group and its page is active and named in the breadcrumb", () => {
  assert.deepEqual(
    DATA_NAV.map((n) => n.label),
    ["Import data"],
  );
  assert.equal(activeHref("/reactivation/import"), "/reactivation/import");
  assert.deepEqual(breadcrumb("/reactivation/import"), ["Workspace", "Import data"]);
});
