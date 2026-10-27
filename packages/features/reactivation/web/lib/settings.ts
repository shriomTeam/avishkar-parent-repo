/**
 * The Settings form's logic, free of React so `node --test` can check it (see web/unit). The form edits a short list
 * of the saved settings; everything else in the saved config is sent back untouched, and the server validates it all.
 * The limits here only give quick, friendly errors.
 */
import type { Schemas } from "@clinic/api-client";

type DeepRequired<T> = T extends object ? { [K in keyof T]-?: DeepRequired<Exclude<T[K], undefined>> } : T;
/** The saved config. The API schema marks fields with defaults as optional, but it always sends all of them. */
export type Config = DeepRequired<Schemas["ReactivationSettings"]>;

export type FieldKey =
  | "dormantDays"
  | "intervalDays"
  | "topPercent"
  | "topDollars"
  | "oneAndDoneDays"
  | "churnMonths"
  | "rateLow"
  | "rateHigh";

export type GroupKey =
  | "lapsed_high_value"
  | "churned_member"
  | "consult_not_converted"
  | "overdue_maintenance"
  | "one_and_done"
  | "lapsed_regular"
  | "unused_balance";

export type Values = Record<FieldKey, string>;
export type Switches = Record<GroupKey, boolean>;
export type FormState = { values: Values; switches: Switches };

export type FieldDef = {
  key: FieldKey;
  label: string;
  unit: string;
  /** A dollar sign shown before the box. */
  prefix?: string;
  min: number;
  max: number;
  optional?: boolean;
  /** One sentence with an example, written from the number currently in the box. */
  example: (n: number | null) => string;
  /** Always shown under the example. */
  note?: string;
  read: (c: Config) => string;
  write: (c: Config, n: number | null) => void;
};

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);
const dollars = (n: number) => `$${n.toLocaleString("en-US")}`;
/** A percentage as the server holds it (0 to 1), free of float noise. */
const fraction = (percent: number) => Number((percent / 100).toFixed(4));
const percentOf = (f: number) => String(Math.round(f * 10000) / 100);

export const FIELDS: FieldDef[] = [
  {
    key: "dormantDays",
    label: "Count a patient as dormant after",
    unit: "days without a visit",
    min: 1,
    max: 3650,
    example: (n) =>
      n === null ? "" : `A patient who last visited more than ${n} ${plural(n, "day", "days")} ago counts as dormant.`,
    note: "Patients are dormant once they pass whichever is shorter: this number of days or their usual time between visits.",
    read: (c) => String(c.dormant.min_days_since_visit),
    write: (c, n) => void (c.dormant.min_days_since_visit = n as number),
  },
  {
    key: "intervalDays",
    label: "Usual time between visits",
    unit: "days",
    min: 1,
    max: 3650,
    example: (n) =>
      n === null
        ? ""
        : `A patient is overdue once ${n} ${plural(n, "day", "days")} pass without a visit, unless their services have their own time.`,
    read: (c) => String(c.dormant.default_rebooking_days),
    write: (c, n) => void (c.dormant.default_rebooking_days = n as number),
  },
  {
    key: "oneAndDoneDays",
    label: "A patient who came once is dormant after",
    unit: "days",
    min: 1,
    max: 3650,
    example: (n) =>
      n === null
        ? ""
        : `Someone who visited once and hasn't been back for more than ${n} ${plural(n, "day", "days")} counts as One-and-done.`,
    read: (c) => String(c.types.one_and_done.min_days_since_visit),
    write: (c, n) => void (c.types.one_and_done.min_days_since_visit = n as number),
  },
  {
    key: "topPercent",
    label: "Top spenders are the top",
    unit: "% of patients by spend",
    min: 1,
    max: 50,
    example: (n) =>
      n === null ? "" : `With ${n}%, the ${n} in every 100 patients who have spent the most count as top spenders.`,
    read: (c) => String(100 - c.types.lapsed_high_value.spend_percentile_min),
    write: (c, n) => void (c.types.lapsed_high_value.spend_percentile_min = 100 - (n as number)),
  },
  {
    key: "topDollars",
    label: "Also count patients who spent more than",
    unit: "in total",
    prefix: "$",
    min: 1,
    max: 1_000_000,
    optional: true,
    example: (n) =>
      n === null
        ? "Leave this empty to use the percentage above on its own."
        : `A patient who has spent more than ${dollars(n)} in total counts as a top spender, even outside the percentage above.`,
    note: "Total spend is everything the patient has paid in the records, with refunds taken off.",
    read: (c) => {
      const cents = c.types.lapsed_high_value.spend_cents_min;
      return cents === null || cents === undefined ? "" : String(cents / 100);
    },
    write: (c, n) => void (c.types.lapsed_high_value.spend_cents_min = n === null ? null : Math.round(n * 100)),
  },
  {
    key: "churnMonths",
    label: "For a churned member, count their fee for",
    unit: "months",
    min: 1,
    max: 36,
    example: (n) =>
      n === null
        ? ""
        : `The revenue estimate for a Churned member is ${n} ${plural(n, "month", "months")} of their membership fee.`,
    read: (c) => String(c.types.churned_member.membership_months),
    write: (c, n) => void (c.types.churned_member.membership_months = n as number),
  },
  {
    key: "rateLow",
    label: "Lowest share of patients who come back",
    unit: "%",
    min: 0,
    max: 100,
    example: (n) =>
      n === null ? "" : `We assume at least ${n} in every 100 dormant patients could return.`,
    note: "Used when your own past campaigns don't give us a measured rate.",
    read: (c) => percentOf(c.revenue.rate_low),
    write: (c, n) => void (c.revenue.rate_low = fraction(n as number)),
  },
  {
    key: "rateHigh",
    label: "Highest share of patients who come back",
    unit: "%",
    min: 0,
    max: 100,
    example: (n) =>
      n === null ? "" : `We assume up to ${n} in every 100 dormant patients could return.`,
    read: (c) => percentOf(c.revenue.rate_high),
    write: (c, n) => void (c.revenue.rate_high = fraction(n as number)),
  },
];

export const FIELD_BY_KEY = Object.fromEntries(FIELDS.map((f) => [f.key, f])) as Record<FieldKey, FieldDef>;

/** The patient groups, in the order the analysis ranks them. Names match the Overview. */
export const GROUPS: { key: GroupKey; label: string }[] = [
  { key: "lapsed_high_value", label: "Lapsed high-value" },
  { key: "churned_member", label: "Churned member" },
  { key: "consult_not_converted", label: "Consult not converted" },
  { key: "overdue_maintenance", label: "Overdue maintenance" },
  { key: "one_and_done", label: "One-and-done" },
  { key: "lapsed_regular", label: "Lapsed regulars" },
  { key: "unused_balance", label: "Unused balance" },
];

export function formFromConfig(c: Config): FormState {
  const values = Object.fromEntries(FIELDS.map((f) => [f.key, f.read(c)])) as Values;
  const switches = Object.fromEntries(GROUPS.map((g) => [g.key, c.types[g.key].enabled])) as Switches;
  return { values, switches };
}

/** The values as the numbers they stand for: blank is null, anything that is not a whole number is NaN. */
export function parseValue(raw: string): number | null {
  const text = raw.trim();
  if (text === "") return null;
  return /^\d+$/.test(text) ? Number(text) : Number.NaN;
}

/**
 * What is wrong with each box, by field. A box the person has not changed from what is saved is not judged, so a
 * value set some other way (such as 12.5 dollars) never stops an unrelated save.
 */
export function validate(form: FormState, saved: Config): Partial<Record<FieldKey, string>> {
  const errors: Partial<Record<FieldKey, string>> = {};
  for (const f of FIELDS) {
    const raw = form.values[f.key];
    if (raw === f.read(saved)) continue;
    const n = parseValue(raw);
    if (n === null) {
      if (!f.optional) errors[f.key] = "Enter a number.";
    } else if (Number.isNaN(n)) {
      errors[f.key] = "Use a whole number, with no letters, commas or decimals.";
    } else if (n < f.min || n > f.max) {
      errors[f.key] = `Enter a number from ${f.min.toLocaleString("en-US")} to ${f.max.toLocaleString("en-US")}.`;
    }
  }
  const low = parseValue(form.values.rateLow);
  const high = parseValue(form.values.rateHigh);
  if (!errors.rateLow && !errors.rateHigh && low !== null && high !== null && low > high)
    errors.rateHigh = "The highest share can't be lower than the lowest.";
  return errors;
}

/** The saved config with the form's changes written in. Anything the person did not change is left exactly as it was. */
export function applyForm(saved: Config, form: FormState): Config {
  const next = structuredClone(saved);
  for (const f of FIELDS) {
    const raw = form.values[f.key];
    if (raw === f.read(saved)) continue;
    f.write(next, parseValue(raw));
  }
  for (const g of GROUPS) next.types[g.key].enabled = form.switches[g.key];
  return next;
}

export function sameForm(a: FormState, b: FormState): boolean {
  return FIELDS.every((f) => a.values[f.key] === b.values[f.key]) && GROUPS.every((g) => a.switches[g.key] === b.switches[g.key]);
}

/** True when the form already holds the standard values, so Reset has nothing to do. `defaults` come from the server. */
export function isStandard(form: FormState, defaults: Config): boolean {
  return sameForm(form, formFromConfig(defaults));
}

/** "your saved settings (version 3)" or "the standard settings", for sentences about what an analysis uses. */
export function settingsInUse(version: number | null | undefined): string {
  return version ? `your saved settings (version ${version})` : "the standard settings";
}
