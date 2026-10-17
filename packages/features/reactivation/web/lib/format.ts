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
