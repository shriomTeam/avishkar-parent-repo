import test from "node:test";
import assert from "node:assert/strict";

import { describePoints } from "../lib/points.ts";

const money = (c: number) => `$${Math.round(c / 100)}`;
const lines = (points: Record<string, unknown> | null, offer: string | null = "Botox") =>
  Object.fromEntries(describePoints(points, { offerService: offer, money }).map((l) => [l.label, l.text]));

test("nothing switched on gives nothing", () => {
  assert.deepEqual(describePoints({}, { offerService: null, money }), []);
  assert.deepEqual(describePoints(null, { offerService: null, money }), []);
});

test("the suggested service says where it came from", () => {
  assert.equal(lines({ best_offer: { source: "usual_service" } })["Suggested service"], "Botox, their usual service");
  assert.equal(
    lines({ best_offer: { source: "consulted_service" } })["Suggested service"],
    "Botox, the service they had a consult for",
  );
  assert.equal(lines({ best_offer: { service_id: null } }, null)["Suggested service"], "No service is on record for this patient");
});

test("best time: weekday and band, or the plain reason it can't be worked out", () => {
  assert.equal(lines({ best_time: { weekday: 1, band: 3 } })["Best time to reach out"], "They usually book on Tuesdays, late morning");
  assert.equal(lines({ best_time: { weekday: 6, band: 6 } })["Best time to reach out"], "They usually book on Sundays, in the evening");
  assert.match(lines({ best_time: { weekday: null, band: null, reason: "needs_visit_times" } })["Best time to reach out"] ?? "", /Needs visit times/);
  assert.match(lines({ best_time: { weekday: null, band: null, reason: "fewer_than_3_visits" } })["Best time to reach out"] ?? "", /at least 3 visits/);
});

test("provider, seasonality, change and risk", () => {
  const l = lines({
    provider_continuity: { status: "inactive" },
    seasonality: { applies: true, month: 12 },
    change_since_last: { change: "new" },
    revenue_at_risk: { cents: 25_000 },
  });
  assert.equal(l["Usual provider"], "No longer works here");
  assert.equal(l["Seasonal pattern"], "They tend to visit around December");
  assert.equal(l["Since the last analysis"], "Newly dormant");
  assert.equal(l["At risk"], "A typical visit is worth about $250");
  assert.equal(lines({ provider_continuity: { status: "unknown" } })["Usual provider"], "We can't tell whether they still work here");
  assert.equal(lines({ provider_continuity: { status: "active" } })["Usual provider"], "Still works here");
});

test("points that do not apply, or are only for the first run, are left out", () => {
  const l = lines({ seasonality: { applies: false, reason: "window_not_near" }, change_since_last: { change: "first_run" } });
  assert.deepEqual(l, {});
  assert.equal(lines({ change_since_last: { change: "unchanged" } })["Since the last analysis"], "Was already dormant");
});

test("no internal codes leak into the text", () => {
  const all = describePoints(
    { best_offer: { source: "usual_service" }, best_time: { weekday: null, band: null, reason: "needs_visit_times" },
      provider_continuity: { status: "unknown" }, change_since_last: { change: "new" } },
    { offerService: "Botox", money },
  ).map((x) => x.text).join(" ");
  for (const code of ["usual_service", "needs_visit_times", "first_run", "fewer_than"]) assert.ok(!all.includes(code));
});
