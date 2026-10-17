"use client";
import { useState, type ReactNode } from "react";

import { formatAbout, formatDay, formatDaysAgo, formatMoney, formatOverdue } from "../lib/format";
import { LIKELIHOOD_HELP, NOT_SIZED, OVERDUE_HELP, WORTH_HELP } from "../lib/messages";
import {
  BAND_LABEL,
  REACH_LABEL,
  likelihoodBand,
  type Dir,
  type PatientRow,
  type SortKey,
} from "../lib/patient-list";
import { describePoints } from "../lib/points";
import { Hint, NotSized } from "./hint";

function SortHeader({
  label,
  hint,
  sortKey,
  sort,
  dir,
  onSort,
}: {
  label: string;
  hint?: string;
  sortKey: SortKey;
  sort: SortKey;
  dir: Dir;
  onSort: (key: SortKey) => void;
}) {
  const active = sort === sortKey;
  return (
    <th scope="col" aria-sort={active ? (dir === "asc" ? "ascending" : "descending") : "none"} role="columnheader">
      <button type="button" className="dp-sort" onClick={() => onSort(sortKey)} data-testid={`sort-${sortKey}`}>
        {hint ? <Hint text={hint}>{label}</Hint> : label}
        <span aria-hidden className="dp-sort-arrow">
          {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

function Worth({ row }: { row: PatientRow }) {
  if (row.low !== null && row.high !== null) {
    return row.kind === "retention" ? (
      <>
        <span className="dp-money">{formatMoney(row.low)}</span> already paid
      </>
    ) : (
      <span className="dp-money">{formatAbout(row.low, row.high)}</span>
    );
  }
  const reason =
    row.status === "at_risk" ? NOT_SIZED.atRisk : row.primaryType === null ? NOT_SIZED.unclassified : NOT_SIZED.noBasis;
  return <NotSized reason={reason} />;
}

function Why({ row }: { row: PatientRow }) {
  const points = describePoints(row.points, { offerService: row.offerService, money: formatMoney });
  return (
    <div className="dp-why">
      <h3>Why they match</h3>
      <ul className="dp-why-list">
        {row.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      {points.length > 0 && (
        <>
          <h3>What we know about them</h3>
          <dl className="dp-points">
            {points.map((p) => (
              <div key={p.label}>
                <dt>{p.label}</dt>
                <dd>{p.text}</dd>
              </div>
            ))}
            <div>
              <dt>Can be reached</dt>
              <dd>{REACH_LABEL[row.reach]}</dd>
            </div>
          </dl>
        </>
      )}
    </div>
  );
}

export function PatientTable({
  rows,
  sort,
  dir,
  onSort,
  busy,
}: {
  rows: PatientRow[];
  sort: SortKey;
  dir: Dir;
  onSort: (key: SortKey) => void;
  busy: boolean;
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <div className="dp-list" data-busy={busy || undefined}>
      <table className="dp-table dp-patients" role="table" aria-busy={busy} data-testid="patients-table">
        <caption className="dp-visually-hidden">Patients in this group</caption>
        <thead role="rowgroup">
          <tr role="row">
            <th scope="col" role="columnheader">
              Patient
            </th>
            <th scope="col" role="columnheader">
              Last visit
            </th>
            <th scope="col" role="columnheader">
              Usual service
            </th>
            <SortHeader label="How overdue" hint={OVERDUE_HELP} sortKey="overdue" sort={sort} dir={dir} onSort={onSort} />
            <SortHeader label="Likelihood" hint={LIKELIHOOD_HELP} sortKey="likelihood" sort={sort} dir={dir} onSort={onSort} />
            <SortHeader label="Could be worth" hint={WORTH_HELP} sortKey="value" sort={sort} dir={dir} onSort={onSort} />
            <th scope="col" role="columnheader">
              Can be reached
            </th>
          </tr>
        </thead>
        <tbody role="rowgroup">
          {rows.map((row) => {
            const expanded = open.has(row.key);
            const band = likelihoodBand(row.score);
            const panelId = `why-${row.key}`;
            return (
              <RowPair key={row.key} expanded={expanded} panelId={panelId} panel={<Why row={row} />}>
                <td role="cell" data-label="Patient" className="dp-cell-patient">
                  <button
                    type="button"
                    className="dp-expand"
                    aria-expanded={expanded}
                    aria-controls={panelId}
                    onClick={() => toggle(row.key)}
                    data-testid="expand-row"
                  >
                    <span aria-hidden className="dp-expand-arrow" />
                    <span className="dp-patient-name">{row.name}</span>
                  </button>
                  {row.status === "at_risk" && <span className="dp-badge">At risk</span>}
                </td>
                <td role="cell" data-label="Last visit">
                  {row.lastVisitDay ? (
                    <>
                      <span>{formatDay(row.lastVisitDay)}</span>
                      {row.daysSince !== null && <span className="dp-small dp-block">{formatDaysAgo(row.daysSince)}</span>}
                    </>
                  ) : (
                    "Not recorded"
                  )}
                </td>
                <td role="cell" data-label="Usual service">
                  {row.usualService ?? "Not recorded"}
                </td>
                <td role="cell" data-label="How overdue">
                  {row.overdueRatio === null ? "Not available" : formatOverdue(row.overdueRatio)}
                </td>
                <td role="cell" data-label="Likelihood">
                  {band && row.score !== null ? (
                    <Hint text={`${row.score} out of 100. ${LIKELIHOOD_HELP}`}>
                      <span className="dp-band" data-band={band}>
                        {BAND_LABEL[band]}
                      </span>
                    </Hint>
                  ) : (
                    "Not available"
                  )}
                </td>
                <td role="cell" data-label="Could be worth">
                  <Worth row={row} />
                </td>
                <td role="cell" data-label="Can be reached">
                  {REACH_LABEL[row.reach]}
                </td>
              </RowPair>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RowPair({
  children,
  expanded,
  panelId,
  panel,
}: {
  children: ReactNode;
  expanded: boolean;
  panelId: string;
  panel: ReactNode;
}) {
  return (
    <>
      <tr role="row" className="dp-patient-row" data-expanded={expanded || undefined} data-testid="patient-row">
        {children}
      </tr>
      <tr role="row" id={panelId} className="dp-why-row" hidden={!expanded} data-testid="why-row">
        <td role="cell" colSpan={7}>
          {expanded && panel}
        </td>
      </tr>
    </>
  );
}
