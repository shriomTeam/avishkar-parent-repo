/**
 * The settings form's logic, free of React so `node --test` can check it (see web/unit). The server answers a bad
 * body with only "invalid_request", so every rule is mirrored here to give friendly per-field errors. The numbers
 * come from limits.json, and tests/test_web_limits.py checks that file (and the shared rule cases) against the
 * server's own model, so the two cannot drift apart silently. The server stays the authority.
 */
import type { Schemas } from "@clinic/api-client";
import limits from "./limits.json" with { type: "json" };

type DeepRequired<T> = T extends object ? { [K in keyof T]-?: DeepRequired<Exclude<T[K], undefined>> } : T;
/** The saved config. The API schema marks fields with defaults as optional, but it always sends all of them. */
export type Config = DeepRequired<Schemas["LeadResponseSettings"]>;

export type Day = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export const DAYS = limits.days as Day[];
export const DAY_LABELS: Record<Day, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export const LIMITS = limits;
export const ROLES = limits.escalation_roles;
/** What the quiet-hours boxes hold when the person switches quiet hours on. */
export const QUIET_SUGGESTION = { start: "21:00", end: "08:00" };
/** A window the person gets when they open a closed day. */
export const NEW_WINDOW = { start: "09:00", end: "17:00" };

export type WindowForm = { start: string; end: string };
export type FormState = {
  ack: string;
  holding: string;
  sla: string;
  role: string;
  hours: Record<Day, WindowForm[]>;
  quiet: { on: boolean; start: string; end: string };
};

export type Errors = {
  ack?: string;
  holding?: string;
  sla?: string;
  role?: string;
  quiet?: string;
  hours?: Partial<Record<Day, string>>;
};

export function formFromConfig(c: Config): FormState {
  const hours = Object.fromEntries(
    DAYS.map((d) => [d, c.business_hours[d].map((w) => ({ start: w.start, end: w.end }))]),
  ) as Record<Day, WindowForm[]>;
  const q = c.quiet_hours;
  return {
    ack: c.ack_text,
    holding: String(c.holding_minutes),
    sla: String(c.sla_minutes),
    role: c.escalation_role,
    hours,
    quiet: q ? { on: true, start: q.start, end: q.end } : { on: false, ...QUIET_SUGGESTION },
  };
}

/** A box's number: blank is null, anything that is not a whole number is NaN. */
export function parseWhole(raw: string): number | null {
  const text = raw.trim();
  if (text === "") return null;
  return /^\d+$/.test(text) ? Number(text) : Number.NaN;
}

/** Characters the way the server counts them (code points, not UTF-16 units). */
export function charCount(text: string): number {
  return [...text].length;
}

const NOT_PLAIN = /[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/u;
const CLOCK = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;
const range = (min: number, max: number) => `Enter a number from ${min} to ${max}.`;

function wholeError(raw: string, min: number, max: number): string | null {
  const n = parseWhole(raw);
  if (n === null) return "Enter a number.";
  if (Number.isNaN(n)) return "Use a whole number, with no letters or decimals.";
  if (n < min || n > max) return range(min, max);
  return null;
}

function ackError(raw: string): string | null {
  const text = raw.trim();
  const { min_length: min, max_length: max } = limits.ack_text;
  if (charCount(text) < min) return "Write the message a new lead receives.";
  if (charCount(text) > max) return `Shorten this to ${max} characters or fewer. It is ${charCount(text)}.`;
  if (text.includes("{") || text.includes("}"))
    return "Remove the curly brackets { }. Names and other details can't be added to this message.";
  for (const ch of text) if (ch !== "\n" && NOT_PLAIN.test(ch)) return "Use plain text only. Remove special or hidden characters.";
  return null;
}

function dayError(windows: WindowForm[]): string | null {
  if (windows.length > limits.windows_per_day) return `Use at most ${limits.windows_per_day} time ranges a day.`;
  for (const w of windows) {
    if (!CLOCK.test(w.start) || !CLOCK.test(w.end)) return "Set a start and an end time for each range.";
    if (w.start >= w.end) return "Each range must end after it starts.";
  }
  const ordered = [...windows].sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0));
  for (let i = 1; i < ordered.length; i++)
    if (ordered[i]!.start < ordered[i - 1]!.end) return "These time ranges overlap. Change one so they don't.";
  return null;
}

/** What is wrong with each part of the form, by field. Empty when the form can be sent. */
export function validate(form: FormState): Errors {
  const errors: Errors = {};
  const ack = ackError(form.ack);
  if (ack) errors.ack = ack;

  const holding = wholeError(form.holding, limits.holding_minutes.min, limits.holding_minutes.max);
  if (holding) errors.holding = holding;
  const sla = wholeError(form.sla, limits.sla_minutes.min, limits.sla_minutes.max);
  if (sla) errors.sla = sla;
  if (!holding && !sla && parseWhole(form.sla)! <= parseWhole(form.holding)!)
    errors.sla = `The staff response target must be longer than the holding message time (${form.holding.trim()} minutes).`;

  if (!ROLES.includes(form.role)) errors.role = "Choose who is told.";

  for (const day of DAYS) {
    const problem = dayError(form.hours[day]);
    if (problem) (errors.hours ??= {})[day] = problem;
  }

  if (form.quiet.on) {
    if (!CLOCK.test(form.quiet.start) || !CLOCK.test(form.quiet.end)) errors.quiet = "Set a start and an end time.";
    else if (form.quiet.start === form.quiet.end) errors.quiet = "The start and end times must be different.";
  }
  return errors;
}

/** The errors as a flat list for the summary at the top, in page order. `id` is the id of the field to focus. */
export function errorList(errors: Errors): { id: string; label: string; message: string }[] {
  const list: { id: string; label: string; message: string }[] = [];
  if (errors.ack) list.push({ id: "field-ack", label: "Instant reply", message: errors.ack });
  if (errors.holding) list.push({ id: "field-holding", label: "Holding message", message: errors.holding });
  if (errors.sla) list.push({ id: "field-sla", label: "Staff response target", message: errors.sla });
  if (errors.role) list.push({ id: "field-role", label: "Who is told", message: errors.role });
  for (const day of DAYS) {
    const message = errors.hours?.[day];
    if (message) list.push({ id: `field-hours-${day}`, label: `${DAY_LABELS[day]} hours`, message });
  }
  if (errors.quiet) list.push({ id: "field-quiet", label: "Quiet hours", message: errors.quiet });
  return list;
}

/** The saved config with the form written in. Everything the form does not show (the AI settings) stays as it was. */
export function applyForm(saved: Config, form: FormState): Config {
  const next = structuredClone(saved);
  next.ack_text = form.ack.trim();
  next.holding_minutes = Number(form.holding.trim());
  next.sla_minutes = Number(form.sla.trim());
  next.escalation_role = form.role as Config["escalation_role"];
  for (const day of DAYS)
    next.business_hours[day] = [...form.hours[day]]
      .sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0))
      .map((w) => ({ start: w.start, end: w.end }));
  next.quiet_hours = form.quiet.on ? { start: form.quiet.start, end: form.quiet.end } : null;
  return next;
}

export function sameForm(a: FormState, b: FormState): boolean {
  return (
    a.ack === b.ack &&
    a.holding === b.holding &&
    a.sla === b.sla &&
    a.role === b.role &&
    a.quiet.on === b.quiet.on &&
    (!a.quiet.on || (a.quiet.start === b.quiet.start && a.quiet.end === b.quiet.end)) &&
    DAYS.every(
      (d) =>
        a.hours[d].length === b.hours[d].length &&
        a.hours[d].every((w, i) => w.start === b.hours[d][i]!.start && w.end === b.hours[d][i]!.end),
    )
  );
}

/** True when the form already holds the standard values, so Reset has nothing to do. `defaults` come from the server. */
export function isStandard(form: FormState, defaults: Config): boolean {
  return sameForm(form, formFromConfig(defaults));
}
