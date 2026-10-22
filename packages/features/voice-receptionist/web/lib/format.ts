import type { CallSummary } from "./inbound/api";
export const duration = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
export const dateLabel = (date: string, timezone: string) =>
  new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(date));
export function median(values: number[]) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return Math.round(
    sorted.length % 2 ? sorted[mid]! : (sorted[mid - 1]! + sorted[mid]!) / 2,
  );
}
export const plural = (n: number, word: string) =>
  `${n} ${word}${n === 1 ? "" : "s"}`;

export const channelLabel = (channel: string) =>
  channel === "browser_test"
    ? "Browser test"
    : channel === "twilio"
      ? "Phone call"
      : channel;

export const statusLabel = (status: string) =>
  status === "completed"
    ? "Completed"
    : status === "failed"
      ? "Failed"
      : "In progress";

const REASONS: Record<string, string> = {
  caller_hangup: "Caller ended the call",
  agent_ended: "Agent ended the call",
  caller_disconnected: "Caller disconnected",
  max_duration: "Reached the time limit",
  model_disconnected: "Voice service disconnected",
  expired: "Never connected",
  error: "Error",
};
export const reasonLabel = (reason: string | null | undefined) =>
  reason ? (REASONS[reason] ?? reason.replaceAll("_", " ")) : "—";

export const callDuration = (seconds: number | null | undefined) =>
  seconds == null ? "—" : duration(seconds);

export function exportCalls(calls: CallSummary[]) {
  const safeCell = (value: string) => {
    const safe = /^[\s]*[=+@\-]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const rows = [
    [
      "Call ID",
      "Agent",
      "Channel",
      "Started at (UTC)",
      "Duration",
      "Status",
      "How it ended",
      "Details captured",
    ],
    ...calls.map((c) => [
      c.id,
      c.agent_name ?? "",
      channelLabel(c.channel),
      c.started_at,
      callDuration(c.duration_seconds),
      statusLabel(c.status),
      reasonLabel(c.end_reason),
      String(c.captured_count ?? 0),
    ]),
  ];
  const url = URL.createObjectURL(
    new Blob(
      ["\uFEFF" + rows.map((row) => row.map(safeCell).join(",")).join("\r\n")],
      {
        type: "text/csv;charset=utf-8",
      },
    ),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "avishkar-calls.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
