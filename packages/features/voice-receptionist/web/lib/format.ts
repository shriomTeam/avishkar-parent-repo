import type { Call, Variable } from "./types";
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
export function resolvePrompt(
  text: string,
  vars: Variable[],
  runtime: Record<string, string> = {},
) {
  return text.replace(
    /\{\{([a-z][a-z0-9_]*)\}\}/g,
    (match, name) =>
      runtime[name] ??
      vars.find((v) => v.name === name && v.type === "Static")?.value ??
      match,
  );
}
export function exportCalls(calls: Call[]) {
  const safeCell = (value: string) => {
    const safe = /^[\s]*[=+@\-]/.test(value) ? `'${value}` : value;
    return `"${safe.replaceAll('"', '""')}"`;
  };
  const rows = [
    [
      "Call ID",
      "Caller",
      "Phone",
      "Agent",
      "Version",
      "Started at (UTC)",
      "Duration",
      "Status",
      "Outcome",
    ],
    ...calls.map((c) => [
      c.id,
      c.caller,
      c.phone,
      c.agentName,
      String(c.version),
      c.startedAt,
      duration(c.durationSeconds),
      c.status,
      c.outcome,
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
  link.download = "avishkar-sample-calls.csv";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
