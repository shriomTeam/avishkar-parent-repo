/** Every sentence the settings page writes from its numbers, in one place so tests can pin the wording. */
import type { Config, FormState, WindowForm } from "./settings";
import { DAYS, LIMITS, parseWhole } from "./settings";

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** "14:05" as "2:05 pm". Anything that is not a valid clock time gives an empty string. */
export function clock12(time: string): string {
  const m = /^([01][0-9]|2[0-3]):([0-5][0-9])$/.exec(time);
  if (!m) return "";
  const hour = Number(m[1]);
  return `${hour % 12 === 0 ? 12 : hour % 12}:${m[2]} ${hour < 12 ? "am" : "pm"}`;
}

/** A clock time plus minutes, wrapping past midnight. */
export function addMinutes(time: string, minutes: number): string {
  const m = /^(\d\d):(\d\d)$/.exec(time)!;
  const total = (Number(m[1]) * 60 + Number(m[2]) + minutes) % (24 * 60);
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}

export const ROLE_CHOICES: { value: string; label: string; example: string }[] = [
  { value: "office_manager", label: "Office manager", example: "the office manager" },
  { value: "owner", label: "Owner", example: "the owner" },
];

const EXAMPLE_START = "10:00";

/** Under the holding message box. Blank while the box does not hold a valid number. */
export function holdingExample(raw: string): string {
  const n = parseWhole(raw);
  if (n === null || Number.isNaN(n) || n < LIMITS.holding_minutes.min || n > LIMITS.holding_minutes.max) return "";
  return `A lead texts at ${clock12(EXAMPLE_START)} and nobody has replied. At ${clock12(addMinutes(EXAMPLE_START, n))} (after ${n} ${plural(n, "minute", "minutes")}) they get a short holding message.`;
}

/** Under the staff response target box. */
export function slaExample(rawSla: string, role: string): string {
  const n = parseWhole(rawSla);
  if (n === null || Number.isNaN(n) || n < LIMITS.sla_minutes.min || n > LIMITS.sla_minutes.max) return "";
  const who = ROLE_CHOICES.find((r) => r.value === role)?.example ?? "your manager";
  return `If a lead texts at ${clock12(EXAMPLE_START)} and nobody has replied by ${clock12(addMinutes(EXAMPLE_START, n))}, ${who} is told.`;
}

export function ackCounter(length: number): string {
  return `${length} of ${LIMITS.ack_text.max_length} characters`;
}

/** One day's windows as a sentence: "9:00 am to 12:00 pm, 1:00 pm to 5:00 pm" or "Closed". */
export function daySummary(windows: WindowForm[]): string {
  if (windows.length === 0) return "Closed";
  return windows.map((w) => `${clock12(w.start)} to ${clock12(w.end)}`).join(", ");
}

export function hoursExample(hours: FormState["hours"]): string {
  const open = DAYS.filter((d) => hours[d].length > 0).length;
  if (open === 0) return "Your clinic is closed every day. Add a time range to a day to open it.";
  return `Open ${open} ${plural(open, "day", "days")} a week.`;
}

export function quietExample(q: FormState["quiet"], timezone: string): string {
  if (!q.on) return "No quiet hours are set.";
  if (!clock12(q.start) || !clock12(q.end)) return "";
  return `Quiet hours run from ${clock12(q.start)} to ${clock12(q.end)} in your clinic's time zone (${timezone}).`;
}

export function statusLine(version: number): string {
  return version === 0 ? "Using the standard settings." : `Using your saved settings (version ${version}).`;
}

export function savedMessage(version: number): string {
  return `Saved (version ${version}). These settings take effect when lead response is switched on for your clinic.`;
}

export const UNCHANGED_MESSAGE = "Nothing to save. These are already your saved settings.";

const LABELS: [keyof Config, string][] = [
  ["ack_text", "Instant reply wording"],
  ["holding_minutes", "Holding message time"],
  ["sla_minutes", "Staff response target"],
  ["escalation_role", "Who is told"],
  ["business_hours", "Business hours"],
  ["quiet_hours", "Quiet hours"],
];

/** The names (never the values) of what differs between two configs, in page order. */
export function changedSettings(before: Config, after: Config): string[] {
  return LABELS.filter(([key]) => JSON.stringify(before[key]) !== JSON.stringify(after[key])).map(([, label]) => label);
}

export type SaveKind = "stale" | "forbidden" | "ai_not_available" | "invalid" | "failed";

/** What a failed save means. 422 has two shapes: the platform's generic "invalid_request" and our own plain-string code. */
export function classifySave(status: number, detail: unknown): SaveKind {
  if (status === 412) return "stale";
  if (status === 403) return "forbidden";
  if (status === 422) return detail === "ai_settings_not_available_yet" ? "ai_not_available" : "invalid";
  return "failed";
}

export const SAVE_PROBLEMS: Record<SaveKind, { title: string; text: string }> = {
  stale: {
    title: "Settings changed elsewhere. Reload.",
    text: "Someone saved a change while you were editing. Reload to see the latest settings, then make your changes again.",
  },
  forbidden: {
    title: "You can't change these settings.",
    text: "Only the clinic owner or office manager can save changes here. Ask them to make the change.",
  },
  ai_not_available: {
    title: "AI replies aren't available yet.",
    text: "Nothing on this page can switch them on. Reload the page and try again.",
  },
  invalid: {
    title: "We couldn't accept these settings.",
    text: "One of the values isn't allowed. Check each section, then try again.",
  },
  failed: {
    title: "We couldn't save.",
    text: "Nothing was changed. Check your connection and try again.",
  },
};

export const RESET_LABEL = "Reset to standard settings";
export const RESET_NOTE = "The standard settings are filled in. Nothing is saved until you press Save.";
export const COMING_LATER = "Coming later";
export const AI_INTRO = "AI replies are not part of this release. Nothing here is switched on, and nothing on this page can switch it on.";
export const AI_ROWS = [
  "Turn on AI replies",
  "Answer questions",
  "Quote pricing",
  "Show open appointment times",
  "Book, reschedule and cancel",
  "Use a patient's history in replies",
  "Send AI replies without review",
];
