const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const count = new Intl.NumberFormat("en-US");

export const formatMoney = (cents: number) => money.format(cents / 100);
export const formatCount = (n: number) => count.format(n);

/** "$13,000 to $25,000", or one figure when low and high are the same. */
export function formatRange(lowCents: number, highCents: number) {
  return lowCents === highCents
    ? formatMoney(lowCents)
    : `${formatMoney(lowCents)} to ${formatMoney(highCents)}`;
}

export const formatPercent = (rate: number) =>
  `${Math.round(rate * 100)}%`;

export function formatRateRange(low: number, high: number) {
  return low === high
    ? formatPercent(low)
    : `${formatPercent(low)} to ${formatPercent(high)}`;
}

/** A date and time in the clinic's own timezone, e.g. "Oct 17, 2026, 3:05 PM". */
export function formatDateTime(iso: string, timeZone: string) {
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone,
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleString("en-US");
  }
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["day", 86_400],
  ["hour", 3_600],
  ["minute", 60],
];

/** "3 hours ago", "yesterday", "just now". */
export function relativeTime(iso: string, now: Date) {
  const seconds = Math.round((new Date(iso).getTime() - now.getTime()) / 1000);
  if (Math.abs(seconds) < 60) return "just now";
  const rtf = new Intl.RelativeTimeFormat("en-US", { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size)
      return rtf.format(Math.trunc(seconds / size), unit);
  }
  return "just now";
}

/** A clinic-local calendar day ("2026-03-14") as "Mar 14, 2026". The day is not shifted by any timezone. */
export function formatDay(isoDay: string) {
  const d = new Date(`${isoDay}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return isoDay;
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeZone: "UTC" }).format(d);
}

/** "today", "1 day ago", "412 days ago". */
export function formatDaysAgo(days: number) {
  if (days <= 0) return "today";
  return days === 1 ? "1 day ago" : `${count.format(days)} days ago`;
}

/** "2.4× their usual gap". One decimal place, so 1.04 reads "1.0×". */
export function formatOverdue(ratio: number) {
  return `${ratio.toFixed(1)}× their usual gap`;
}

/** "About $340 to $640", or "About $340" when both ends are the same. */
export function formatAbout(lowCents: number, highCents: number) {
  return `About ${formatRange(lowCents, highCents)}`;
}

/** The return-rate basis in plain words, for a type's summary line. */
export function rateBasisText(source: string | null, low: number, high: number) {
  const range = formatRateRange(low, high);
  return source === "measured"
    ? `At your measured return rate of ${range}, from past campaigns`
    : `At an assumed return rate of ${range}`;
}
