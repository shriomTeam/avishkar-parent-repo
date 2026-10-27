import { Stat } from "./kit";

import { formatCount, formatRange } from "../lib/format";
import { num } from "../lib/summary";

export type FileFacts = { rows: number; patients: number; visitDays: number };

/** The three headline tiles. For a file analysis the last tile says what the file held instead of comparing runs. */
export function Tiles({
  summary,
  file,
}: {
  summary: Record<string, unknown> | null;
  file?: FileFacts;
}) {
  const dormant = num(summary, "dormant_count");
  const total = num(summary, "patients_total");
  const low = num(summary, "new_revenue_low_cents");
  const high = num(summary, "new_revenue_high_cents");
  const firstRun = summary?.first_run === true;
  const newly = num(summary, "newly_dormant");
  const back = num(summary, "returned_since_last");
  return (
    <div className="dp-tiles" data-testid="tiles">
      <div data-testid="tile-dormant">
        <Stat
          lead={!file}
          label="Dormant patients"
          value={dormant === null ? "Not available" : formatCount(dormant)}
          hint={
            total === null
              ? undefined
              : `of ${formatCount(total)} ${total === 1 ? "patient" : "patients"}`
          }
        />
      </div>
      <div data-testid="tile-revenue">
        <Stat
          label="Recoverable revenue"
          value={
            low === null || high === null
              ? "Not available"
              : formatRange(low, high)
          }
          hint="New revenue if some of them come back. Prepaid balances aren't included."
        />
      </div>
      <div data-testid="tile-change">
        {file ? (
          <Stat
            label="From your file"
            value={`${formatCount(file.patients)} ${file.patients === 1 ? "patient" : "patients"}`}
            hint={`${formatCount(file.rows)} rows and ${formatCount(file.visitDays)} visits. Nothing is compared with earlier analyses.`}
          />
        ) : (
        <Stat
          label="Since last run"
          value={
            firstRun
              ? "First analysis"
              : newly === null
                ? "Not available"
                : `${formatCount(newly)} newly dormant`
          }
          hint={
            firstRun
              ? "There's no earlier analysis to compare with yet."
              : back === null
                ? undefined
                : `${formatCount(back)} came back`
          }
        />
        )}
      </div>
    </div>
  );
}
