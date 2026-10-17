import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_STATE,
  LIKELIHOOD_BANDS,
  PAGE_SIZE,
  apiParams,
  applyList,
  clampPage,
  clearFilters,
  hasStatusFilter,
  isFiltered,
  likelihoodBand,
  localDay,
  pageCount,
  parseUrlState,
  reachFromPoints,
  rowFromFile,
  rowFromSaved,
  serializeUrlState,
  typeHref,
  type FilePatientInput,
  type ListState,
  type PatientRow,
  type SavedPatientInput,
} from "../lib/patient-list.ts";

const common = {
  status: "dormant",
  primary_type: "one_and_done",
  reasons: ["Last visit 200 days ago"],
  usual_service_name: "Botox",
  days_since_last_visit: 200,
  likelihood_score: 50,
  revenue_basis_cents: 10_000,
  overdue_ratio: 2.4,
  revenue_kind: "new",
  revenue_low_cents: 800,
  revenue_high_cents: 1500,
  offer_service_name: "Botox",
  points: { reachable: { either: true, email: true, sms: false } },
};

const saved = (over: Partial<SavedPatientInput> = {}): SavedPatientInput => ({
  ...common,
  patient_id: "0a1b2c3d-1111-2222-3333-444455556666",
  display_name: "Maya Rao",
  last_visit_at: "2026-03-14T01:30:00Z",
  ...over,
});
const file = (over: Partial<FilePatientInput> = {}): FilePatientInput => ({
  ...common,
  patient_id: "uuid-of-p1",
  external_id: "P-1001",
  display_name: "Maya Rao",
  last_visit_day: "2026-03-14",
  ...over,
});

// --- the likelihood band ------------------------------------------------------------------------------------------

test("likelihood bands: High 65 and over, Medium 45 to 64, Low under 45", () => {
  assert.deepEqual(LIKELIHOOD_BANDS, { high: 65, medium: 45 });
  const cases: [number, string][] = [[100, "high"], [65, "high"], [64, "medium"], [45, "medium"], [44, "low"], [0, "low"]];
  for (const [score, band] of cases) assert.equal(likelihoodBand(score), band, `score ${score}`);
  assert.equal(likelihoodBand(null), null);
  assert.equal(likelihoodBand(undefined), null);
});

// --- reachability ---------------------------------------------------------------------------------------------------

test("reachability from the reachable point", () => {
  const r = (email: boolean, sms: boolean) => reachFromPoints({ reachable: { email, sms, either: email || sms } });
  assert.equal(r(true, true), "both");
  assert.equal(r(true, false), "email");
  assert.equal(r(false, true), "text");
  assert.equal(r(false, false), "none");
  assert.equal(reachFromPoints({}), "unknown"); // the point is switched off
  assert.equal(reachFromPoints({ reachable: "yes" }), "unknown");
  assert.equal(reachFromPoints({ reachable: { email: true } }), "unknown");
  assert.equal(reachFromPoints(null), "unknown");
});

// --- rows from both sources ------------------------------------------------------------------------------------------

test("a saved row uses the clinic's local day, not the UTC day", () => {
  assert.equal(localDay("2026-03-14T01:30:00Z", "America/New_York"), "2026-03-13");
  assert.equal(localDay("2026-03-14T01:30:00Z", "Asia/Tokyo"), "2026-03-14");
  assert.equal(localDay("nonsense", "UTC"), null);
  assert.equal(rowFromSaved(saved(), "America/New_York").lastVisitDay, "2026-03-13");
  assert.equal(rowFromSaved(saved({ last_visit_at: null }), "UTC").lastVisitDay, null);
});

test("a patient with no name is shown as Patient plus a short id", () => {
  const a = rowFromSaved(saved({ display_name: null }), "UTC");
  assert.deepEqual([a.name, a.hasName], ["Patient 0a1b2c3d", false]);
  const b = rowFromFile(file({ display_name: "  " }));
  assert.deepEqual([b.name, b.hasName], ["Patient P-1001", false]);
  const c = rowFromFile(file());
  assert.deepEqual([c.name, c.hasName, c.lastVisitDay, c.reach, c.low, c.high], ["Maya Rao", true, "2026-03-14", "email", 800, 1500]);
});

// --- the controls and the URL -----------------------------------------------------------------------------------------

test("URL state: defaults leave the URL bare and the search text is never in it", () => {
  assert.equal(serializeUrlState(DEFAULT_STATE), "");
  const state: ListState = { q: "maya", status: "all", reachable: true, sort: "value", dir: "asc", page: 3 };
  const url = serializeUrlState(state);
  assert.equal(url, "?status=all&reachable=1&sort=value&dir=asc&page=3");
  assert.ok(!url.includes("maya"));
  assert.deepEqual(parseUrlState(new URLSearchParams(url)), { ...state, q: "" });
});

test("URL state: bad or missing values fall back to the defaults", () => {
  const parse = (s: string) => parseUrlState(new URLSearchParams(s));
  assert.deepEqual(parse(""), DEFAULT_STATE);
  assert.deepEqual(parse("sort=name&dir=up&status=zzz&page=-4&reachable=yes"), DEFAULT_STATE);
  assert.equal(parse("page=abc").page, 1);
  assert.equal(parse("page=0").page, 1);
  assert.equal(parse("page=7").page, 7);
  assert.equal(parse("q=maya").q, "");
});

test("the API parameters follow the state and the page", () => {
  assert.deepEqual(apiParams("one_and_done", { ...DEFAULT_STATE, page: 3 }), {
    type: "one_and_done", sort: "likelihood", dir: "desc", limit: PAGE_SIZE, offset: 50,
  });
  // A typed page never sends a status; Unclassified sends it unless it is "all".
  assert.equal("status" in apiParams("one_and_done", { ...DEFAULT_STATE, status: "at_risk" }), false);
  assert.equal(apiParams("unclassified", DEFAULT_STATE).status, "dormant");
  assert.equal(apiParams("unclassified", { ...DEFAULT_STATE, status: "at_risk" }).status, "at_risk");
  assert.equal("status" in apiParams("unclassified", { ...DEFAULT_STATE, status: "all" }), false);
  const all = apiParams("one_and_done", { ...DEFAULT_STATE, q: "  maya ", reachable: true, sort: "overdue", dir: "asc" });
  assert.deepEqual([all.q, all.reachable, all.sort, all.dir], ["maya", true, "overdue", "asc"]);
  assert.equal("q" in apiParams("one_and_done", { ...DEFAULT_STATE, q: "   " }), false);
});

test("paging helpers and the filter flags", () => {
  assert.equal(pageCount(0), 1);
  assert.equal(pageCount(25), 1);
  assert.equal(pageCount(26), 2);
  assert.equal(clampPage(9, 60), 3);
  assert.equal(clampPage(0, 60), 1);
  assert.equal(hasStatusFilter("unclassified"), true);
  assert.equal(hasStatusFilter("one_and_done"), false);
  assert.equal(isFiltered(DEFAULT_STATE, "one_and_done"), false);
  assert.equal(isFiltered({ ...DEFAULT_STATE, q: "x" }, "one_and_done"), true);
  assert.equal(isFiltered({ ...DEFAULT_STATE, reachable: true }, "one_and_done"), true);
  assert.equal(isFiltered({ ...DEFAULT_STATE, status: "all" }, "one_and_done"), false); // no filter there
  assert.equal(isFiltered({ ...DEFAULT_STATE, status: "all" }, "unclassified"), true);
  assert.deepEqual(clearFilters({ ...DEFAULT_STATE, q: "x", reachable: true, status: "all", sort: "value", page: 4 }), {
    ...DEFAULT_STATE, sort: "value",
  });
});

test("links to a type page carry the file marker only for file results", () => {
  assert.equal(typeHref("one_and_done", false), "/reactivation/types/one_and_done");
  assert.equal(typeHref("one_and_done", true), "/reactivation/types/one_and_done?source=file");
});

// --- filter, sort and page in the browser ------------------------------------------------------------------------------

function rows(n: number, over: (i: number) => Partial<FilePatientInput> = () => ({})): PatientRow[] {
  return Array.from({ length: n }, (_, i) =>
    rowFromFile(
      file({
        patient_id: `id-${i}`,
        external_id: `P-${1000 + i}`,
        display_name: `Person ${String(i).padStart(3, "0")}`,
        likelihood_score: 90 - i,
        revenue_basis_cents: 1000 + i,
        overdue_ratio: 1 + i / 10,
        ...over(i),
      }),
    ),
  );
}
const names = (r: { items: PatientRow[] }) => r.items.map((x) => x.name);

test("file list: only this type's patients, in the engine's order, 25 to a page", () => {
  const all = [...rows(60), ...rows(5, (i) => ({ primary_type: "lapsed_regular", patient_id: `o${i}` }))];
  const first = applyList(all, "one_and_done", DEFAULT_STATE);
  assert.equal(first.total, 60);
  assert.equal(first.items.length, 25);
  assert.equal(first.items[0]?.name, "Person 000");
  const third = applyList(all, "one_and_done", { ...DEFAULT_STATE, page: 3 });
  assert.equal(third.items.length, 10);
  assert.equal(third.items[0]?.name, "Person 050");
  assert.equal(applyList(all, "one_and_done", { ...DEFAULT_STATE, page: 99 }).page, 3); // clamped
  assert.equal(applyList(all, "lapsed_regular", DEFAULT_STATE).total, 5);
  assert.equal(applyList(all, "overdue_maintenance", DEFAULT_STATE).total, 0);
});

test("file list: search by name or by the id the file used, ignoring case", () => {
  const all = rows(30);
  assert.deepEqual(names(applyList(all, "one_and_done", { ...DEFAULT_STATE, q: "PERSON 007" })), ["Person 007"]);
  assert.deepEqual(names(applyList(all, "one_and_done", { ...DEFAULT_STATE, q: "p-1012" })), ["Person 012"]);
  assert.equal(applyList(all, "one_and_done", { ...DEFAULT_STATE, q: "p-10" }).total, 30); // an id prefix
  assert.equal(applyList(all, "one_and_done", { ...DEFAULT_STATE, q: "zzz" }).total, 0);
  const unnamed = rows(2, () => ({ display_name: null }));
  assert.equal(applyList(unnamed, "one_and_done", { ...DEFAULT_STATE, q: "P-1001" }).total, 1);
});

test("file list: reachable only and the unclassified status filter", () => {
  const all = rows(6, (i) => ({
    points: i % 2 ? { reachable: { email: false, sms: false, either: false } } : { reachable: { email: true, sms: true, either: true } },
  }));
  assert.equal(applyList(all, "one_and_done", { ...DEFAULT_STATE, reachable: true }).total, 3);
  const mixed = rows(5, (i) => ({ primary_type: null, status: i < 2 ? "at_risk" : "dormant" }));
  assert.equal(applyList(mixed, "unclassified", DEFAULT_STATE).total, 3); // dormant by default
  assert.equal(applyList(mixed, "unclassified", { ...DEFAULT_STATE, status: "at_risk" }).total, 2);
  assert.equal(applyList(mixed, "unclassified", { ...DEFAULT_STATE, status: "all" }).total, 5);
  // a typed page ignores a status in its state
  assert.equal(applyList(rows(4), "one_and_done", { ...DEFAULT_STATE, status: "at_risk" }).total, 4);
});

test("file list: sort by value, likelihood and overdue, both ways, ties keep the engine's order", () => {
  const all = rows(5, (i) => ({
    likelihood_score: [50, 70, 50, 70, 60][i] ?? 0,
    revenue_basis_cents: [300, 100, 300, 500, 200][i] ?? 0,
    overdue_ratio: [1.5, null, 3.0, 2.0, 2.0][i] ?? null,
  }));
  const by = (sort: ListState["sort"], dir: ListState["dir"]) =>
    names(applyList(all, "one_and_done", { ...DEFAULT_STATE, sort, dir })).map((n) => Number(n.slice(-3)));
  assert.deepEqual(by("likelihood", "desc"), [1, 3, 4, 0, 2]);
  assert.deepEqual(by("likelihood", "asc"), [0, 2, 4, 1, 3]);
  assert.deepEqual(by("value", "desc"), [3, 0, 2, 4, 1]);
  assert.deepEqual(by("value", "asc"), [1, 4, 0, 2, 3]);
  assert.deepEqual(by("overdue", "desc"), [2, 3, 4, 0, 1]); // the missing ratio is last
  assert.deepEqual(by("overdue", "asc"), [0, 3, 4, 2, 1]); // and last again
});

test("file list: filtering resets nothing by itself, and the page is clamped to what is left", () => {
  const all = rows(60);
  const result = applyList(all, "one_and_done", { ...DEFAULT_STATE, q: "person 05", page: 3 });
  assert.equal(result.total, 10);
  assert.equal(result.page, 1);
  assert.equal(result.items.length, 10);
});
