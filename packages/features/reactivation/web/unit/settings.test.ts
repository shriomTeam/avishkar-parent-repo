import test from "node:test";
import assert from "node:assert/strict";

import {
  applyForm,
  formFromConfig,
  GROUPS,
  isStandard,
  parseValue,
  sameForm,
  settingsInUse,
  validate,
  FIELDS,
  type Config,
} from "../lib/settings.ts";

/** The server's defaults, as GET /settings sends them. */
function defaults(): Config {
  const rule = (priority: number) => ({ enabled: true, priority });
  return {
    dormant: {
      min_days_since_visit: 180,
      default_rebooking_days: 120,
      rebooking_days_by_category: {},
      rebooking_days_by_service: {},
      at_risk_ratio_min: 0.8,
    },
    types: {
      lapsed_high_value: { ...rule(1), spend_percentile_min: 80, spend_cents_min: null, overdue_ratio_min: 2 },
      churned_member: { ...rule(2), membership_months: 6 },
      consult_not_converted: { ...rule(3), conversion_window_days: 60 },
      overdue_maintenance: { ...rule(4), min_visits: 2, overdue_ratio_min: 1, overdue_ratio_max: 2 },
      one_and_done: { ...rule(5), min_days_since_visit: 90 },
      lapsed_regular: rule(5),
      unused_balance: rule(6),
    },
    revenue: { rate_low: 0.08, rate_high: 0.15, min_sample: 30, attribution_window_days: 30 },
  } as unknown as Config;
}

test("the form starts from the saved numbers, in the words the person sees", () => {
  const f = formFromConfig(defaults());
  assert.deepEqual(f.values, {
    dormantDays: "180",
    intervalDays: "120",
    oneAndDoneDays: "90",
    topPercent: "20",
    topDollars: "",
    churnMonths: "6",
    rateLow: "8",
    rateHigh: "15",
  });
  assert.ok(GROUPS.every((g) => f.switches[g.key]));
});

test("nothing changed means nothing is written: the config comes back exactly as it was", () => {
  const c = defaults();
  assert.deepEqual(applyForm(c, formFromConfig(c)), c);
});

test("each box writes the right setting", () => {
  const c = defaults();
  const f = formFromConfig(c);
  f.values.dormantDays = "200";
  f.values.intervalDays = "100";
  f.values.oneAndDoneDays = "60";
  f.values.topPercent = "10";
  f.values.topDollars = "5000";
  f.values.churnMonths = "12";
  f.values.rateLow = "5";
  f.values.rateHigh = "20";
  f.switches.one_and_done = false;
  const n = applyForm(c, f);
  assert.equal(n.dormant.min_days_since_visit, 200);
  assert.equal(n.dormant.default_rebooking_days, 100);
  assert.equal(n.types.one_and_done.min_days_since_visit, 60);
  assert.equal(n.types.lapsed_high_value.spend_percentile_min, 90);
  assert.equal(n.types.lapsed_high_value.spend_cents_min, 500000);
  assert.equal(n.types.churned_member.membership_months, 12);
  assert.equal(n.revenue.rate_low, 0.05);
  assert.equal(n.revenue.rate_high, 0.2);
  assert.equal(n.types.one_and_done.enabled, false);
  assert.equal(c.types.one_and_done.enabled, true, "the saved config is not edited in place");
});

test("emptying the dollar box removes the cutoff", () => {
  const c = defaults();
  c.types.lapsed_high_value.spend_cents_min = 250000;
  const f = formFromConfig(c);
  assert.equal(f.values.topDollars, "2500");
  f.values.topDollars = " ";
  assert.equal(applyForm(c, f).types.lapsed_high_value.spend_cents_min, null);
});

test("settings the form does not show are sent back untouched", () => {
  const c = defaults();
  c.dormant.rebooking_days_by_category = { botox: 90 };
  c.revenue.rate_low = 0.085; // set some other way: not a whole percent
  const f = formFromConfig(c);
  f.values.dormantDays = "200";
  const n = applyForm(c, f);
  assert.deepEqual(n.dormant.rebooking_days_by_category, { botox: 90 });
  assert.equal(n.revenue.rate_low, 0.085);
  assert.deepEqual(validate(f, c), {});
});

test("every box has a plain error for a bad number", () => {
  const c = defaults();
  const f = formFromConfig(c);
  f.values.dormantDays = "0";
  f.values.intervalDays = "abc";
  f.values.oneAndDoneDays = "";
  f.values.topPercent = "51";
  f.values.topDollars = "1,000";
  f.values.churnMonths = "37";
  f.values.rateLow = "-1";
  f.values.rateHigh = "101";
  const e = validate(f, c);
  assert.equal(e.dormantDays, "Enter a number from 1 to 3,650.");
  assert.match(e.intervalDays!, /whole number/);
  assert.equal(e.oneAndDoneDays, "Enter a number.");
  assert.equal(e.topPercent, "Enter a number from 1 to 50.");
  assert.match(e.topDollars!, /whole number/);
  assert.equal(e.churnMonths, "Enter a number from 1 to 36.");
  assert.match(e.rateLow!, /whole number/);
  assert.equal(e.rateHigh, "Enter a number from 0 to 100.");
});

test("the lowest share cannot be higher than the highest", () => {
  const c = defaults();
  const f = formFromConfig(c);
  f.values.rateLow = "30";
  assert.equal(validate(f, c).rateHigh, "The highest share can't be lower than the lowest.");
  f.values.rateHigh = "30";
  assert.deepEqual(validate(f, c), {});
});

test("the dollar box is the only optional one", () => {
  assert.deepEqual(FIELDS.filter((f) => f.optional).map((f) => f.key), ["topDollars"]);
  assert.equal(parseValue(""), null);
  assert.equal(parseValue("12"), 12);
  assert.ok(Number.isNaN(parseValue("1.5")));
});

test("examples are written from the number in the box", () => {
  const byKey = Object.fromEntries(FIELDS.map((f) => [f.key, f]));
  assert.equal(
    byKey.dormantDays!.example(150),
    "A patient who last visited more than 150 days ago counts as dormant.",
  );
  assert.match(byKey.topDollars!.example(5000), /more than \$5,000 in total counts as a top spender/);
  assert.match(byKey.topDollars!.example(null), /Leave this empty/);
  assert.match(byKey.dormantDays!.note!, /whichever is shorter/);
});

test("reset: the form is standard only when every box and switch equals the defaults", () => {
  const d = defaults();
  const f = formFromConfig(d);
  assert.ok(isStandard(f, d));
  f.switches.lapsed_regular = false;
  assert.ok(!isStandard(f, d));
  assert.ok(!sameForm(f, formFromConfig(d)));
});

test("a sentence about the settings in use", () => {
  assert.equal(settingsInUse(0), "the standard settings");
  assert.equal(settingsInUse(null), "the standard settings");
  assert.equal(settingsInUse(3), "your saved settings (version 3)");
});
