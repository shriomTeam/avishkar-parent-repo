import { entryCount, flag, obj, strings } from "./summary";
import { formatCount } from "./format";

/** Plain-language description of where an in-flight run is. */
export function stageLabel(status: string, progressPct: number) {
  if (status === "queued") return "Waiting to start";
  if (progressPct < 10) return "Getting started";
  if (progressPct < 60) return "Reading your patient records";
  if (progressPct < 100) return "Working out who is dormant and what they could be worth";
  return "Saving the results";
}

const FAILURES: Record<string, string> = {
  timed_out:
    "The analysis took too long and was stopped. Your previous results are still shown. Please try again.",
  too_many_patient_errors:
    "Too many patient records had problems, so the analysis was stopped. Your previous results are still shown. Check your imported data, then try again.",
  invariant_failed:
    "The numbers didn't add up, so we didn't save them. Your previous results are still shown. Please try again, and contact support if it keeps happening.",
  bad_timezone:
    "Your clinic's time zone isn't recognised, so the analysis couldn't run. Please contact support.",
  bad_settings:
    "The saved settings for this analysis are no longer valid. Review your settings, then try again.",
  facts_query_failed:
    "We couldn't read your patient records. Your previous results are still shown. Please try again in a few minutes.",
  internal_error:
    "Something went wrong on our side. Your previous results are still shown. Please try again.",
};

export function failureMessage(code: string | null | undefined) {
  return (
    (code && FAILURES[code]) ||
    "The analysis didn't finish. Your previous results are still shown. Please try again."
  );
}

const UNAVAILABLE_REASONS: Record<string, string> = {
  churned_member: "No membership records have been imported.",
  unused_balance: "No membership or prepaid package records have been imported.",
  consult_not_converted: "No consultation visits were found in your records.",
  lapsed_high_value:
    "There aren't enough paying patients yet to tell who your top spenders are.",
};

export function unavailableReason(typeKey: string) {
  return (
    UNAVAILABLE_REASONS[typeKey] ??
    "The records needed to measure this type haven't been imported."
  );
}

export type Note = { tone: "info" | "warn"; text: string };

const WARNINGS: Record<string, string> = {
  data_looks_incomplete:
    "Most patients have no completed visits on record, so your data may be incomplete and the numbers could be low.",
  appointment_status_not_maintained:
    "Many past appointments are still marked as booked, so appointment statuses may not be kept up to date.",
  cohort_too_small_for_percentile:
    "There are too few patients to rank by spend, so top-spender results are limited.",
  no_types_enabled:
    "No patient types are switched on, so nothing could be sized.",
  no_patients: "No patients were found in your records.",
};

const plural = (n: number, one: string, many: string) =>
  `${formatCount(n)} ${n === 1 ? one : many}`;

/** Quality notes in plain words: data gaps, flags that cannot be imported, incomplete data. */
export function qualityNotes(quality: Record<string, unknown> | null): Note[] {
  if (!quality) return [];
  const notes: Note[] = [];
  const available = obj(quality, "data_available");
  const gaps: [string, string][] = [
    ["memberships", "No membership or package records were found, so Churned member and Unused balance can't be measured."],
    ["staff", "Staff records haven't been imported, so we can't tell whether a patient's usual provider still works here."],
    ["consents", "No messaging-consent records were found, so we can't tell who has opted out of texts or emails."],
    ["services", "Visits aren't linked to services, so usual services and offers can't be worked out."],
  ];
  for (const [key, text] of gaps)
    if (flag(available, key) === false) notes.push({ tone: "warn", text });

  if (flag(quality, "exclusion_flags_not_importable"))
    notes.push({
      tone: "warn",
      text: "\"Do not contact\" and \"deceased\" flags can't be imported yet, so patients who asked not to be contacted may still appear in these results. Check with your team before contacting anyone.",
    });

  for (const code of strings(quality, "warnings"))
    notes.push({
      tone: "warn",
      text:
        WARNINGS[code] ??
        "Another data issue was noticed during the analysis.",
    });

  const left: [string, string, string][] = [
    ["excluded_minor", "patient under 18 was left out", "patients under 18 were left out"],
    ["excluded_do_not_contact", "patient marked do-not-contact was left out", "patients marked do-not-contact were left out"],
    ["excluded_deceased", "patient marked deceased was left out", "patients marked deceased were left out"],
    ["no_completed_visits", "patient has no completed visits and wasn't assessed", "patients have no completed visits and weren't assessed"],
    ["patient_errors", "patient couldn't be assessed because of a problem in their record", "patients couldn't be assessed because of problems in their records"],
    ["missing_service_on_visits", "patient has visits with no service recorded", "patients have visits with no service recorded"],
  ];
  for (const [key, one, many] of left) {
    const n = entryCount(quality, key);
    if (n > 0) notes.push({ tone: "info", text: plural(n, one, many) + "." });
  }
  return notes;
}
