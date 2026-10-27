import test from "node:test";
import assert from "node:assert/strict";

import { PATHS, showingFile, statusOf } from "../components/shell-status.ts";
import { FILE_PATH, IMPORT_PATH, ROOT } from "../components/shell-nav.ts";

test("a saved analysis, a file, nothing yet and an unknown check each say their own thing", () => {
  const saved = statusOf("saved", false);
  assert.deepEqual([saved.tone, saved.badge, saved.title], ["saved", "Saved data", "Saved analysis"]);
  assert.match(saved.text, /last saved analysis/);

  const file = statusOf("saved", true);
  assert.deepEqual([file.tone, file.badge, file.title], ["file", "From file", "File results"]);
  assert.match(file.text, /Not saved/);
  assert.match(file.footer, /not saved/);

  const none = statusOf("none", false);
  assert.deepEqual([none.tone, none.badge, none.title], ["none", "No saved data", "No analysis yet"]);
});

test("nothing but a saved analysis ever claims one", () => {
  for (const [saved, file] of [["none", false], ["unknown", false], ["none", true], ["unknown", true], ["saved", true]] as const) {
    const s = statusOf(saved, file);
    assert.doesNotMatch(`${s.title} ${s.text} ${s.footer}`, /last saved analysis|Saved analysis/, `${saved} ${file}`);
  }
  assert.doesNotMatch(statusOf("unknown", false).text, /analysed|saved/i);
});

test("a file wins over a saved analysis, and an unknown check says nothing about the data", () => {
  assert.equal(statusOf("none", true).tone, "file");
  assert.equal(statusOf("unknown", false).tone, "unknown");
});

test("a page shows the file only where it says so", () => {
  assert.equal(showingFile("/reactivation", null, null, true), true);
  assert.equal(showingFile("/reactivation", "saved", null, true), false); // ?view=saved
  assert.equal(showingFile("/reactivation/types/one_and_done", null, "file", true), true);
  assert.equal(showingFile("/reactivation/types/one_and_done", null, null, true), false);
  assert.equal(showingFile("/reactivation/file", null, null, true), true);
  assert.equal(showingFile("/reactivation/import", null, null, true), true);
  assert.equal(showingFile("/reactivation/runs", null, null, true), false);
  assert.equal(showingFile("/reactivation/settings", null, null, true), false);
  assert.equal(showingFile("/reactivation", null, null, false), false);
  assert.equal(showingFile("/reactivation/file", null, null, false), false);
});

test("the paths written out in shell-status are the ones shell-nav uses", () => {
  assert.deepEqual(PATHS, { root: ROOT, file: FILE_PATH, import: IMPORT_PATH });
});
