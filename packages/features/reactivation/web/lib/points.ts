/**
 * The analysis points shown under "Why they match", in plain words. Pure (no imports) so it can be unit tested
 * with `node --test`. A point that is switched off, or that does not apply, produces no line.
 */

export type PointLine = { label: string; text: string };

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
]; // fmt: skip
// The engine groups visit times into 3-hour bands: band 0 is midnight to 3 am.
const BANDS = ["after midnight", "in the early morning", "in the morning", "late morning", "early afternoon", "in the late afternoon", "in the evening", "late evening"];

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

export function describePoints(
  points: Record<string, unknown> | null | undefined,
  opts: { offerService: string | null; money: (cents: number) => string },
): PointLine[] {
  const out: PointLine[] = [];
  const p = points ?? {};

  const offer = p.best_offer;
  if (isObject(offer)) {
    const how = offer.source === "consulted_service" ? "the service they had a consult for" : "their usual service";
    out.push({
      label: "Suggested service",
      text: opts.offerService ? `${opts.offerService}, ${how}` : "No service is on record for this patient",
    });
  }

  const time = p.best_time;
  if (isObject(time)) {
    const day = typeof time.weekday === "number" ? WEEKDAYS[time.weekday] : undefined;
    const band = typeof time.band === "number" ? BANDS[time.band] : undefined;
    if (day && band) out.push({ label: "Best time to reach out", text: `They usually book on ${day}s, ${band}` });
    else if (time.reason === "needs_visit_times")
      out.push({ label: "Best time to reach out", text: "Needs visit times, which a file doesn't include" });
    else out.push({ label: "Best time to reach out", text: "Needs at least 3 visits to tell" });
  }

  const provider = p.provider_continuity;
  if (isObject(provider)) {
    out.push({
      label: "Usual provider",
      text:
        provider.status === "active"
          ? "Still works here"
          : provider.status === "inactive"
            ? "No longer works here"
            : "We can't tell whether they still work here",
    });
  }

  const season = p.seasonality;
  if (isObject(season) && season.applies === true && typeof season.month === "number") {
    const month = MONTHS[season.month - 1];
    if (month) out.push({ label: "Seasonal pattern", text: `They tend to visit around ${month}` });
  }

  const change = p.change_since_last;
  if (isObject(change)) {
    if (change.change === "new") out.push({ label: "Since the last analysis", text: "Newly dormant" });
    else if (change.change === "unchanged")
      out.push({ label: "Since the last analysis", text: "Was already dormant" });
  }

  const risk = p.revenue_at_risk;
  if (isObject(risk) && typeof risk.cents === "number")
    out.push({ label: "At risk", text: `A typical visit is worth about ${opts.money(risk.cents)}` });

  return out;
}
