"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { TypeEntry } from "../lib/api-types";
import {
  formatCount,
  formatMoney,
  formatRange,
  formatRateRange,
} from "../lib/format";
import { NOT_SIZED, unavailableReason } from "../lib/messages";
import { NotSized } from "./hint";
import { typeHref } from "../lib/patient-list";
import { RangeBar } from "./kit";

export function TypesTable({ types, source = "saved" }: { types: TypeEntry[]; source?: "saved" | "file" }) {
  const router = useRouter();
  const scale = Math.max(
    0,
    ...types
      .filter((t) => t.available && t.kind === "new")
      .map((t) => t.revenue_high_cents ?? 0),
  );
  return (
    <div className="dp-table-wrap">
      <table className="dp-table" data-testid="types-table">
        <thead>
          <tr>
            <th scope="col">Patient type</th>
            <th scope="col" className="dp-num">
              Patients
            </th>
            <th scope="col">Could be worth</th>
            <th scope="col">Top service</th>
            <th scope="col" className="dp-chevron">
              <span className="dp-visually-hidden">Open</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {types.map((t) => {
            const href = typeHref(t.type_key, source === "file");
            return (
              <tr
                key={t.type_key}
                data-link
                data-testid={`type-row-${t.type_key}`}
                onClick={(e) => {
                  if (!(e.target as HTMLElement).closest("a")) router.push(href);
                }}
              >
                <td>
                  <Link href={href} className="dp-type-link">
                    {t.label}
                  </Link>
                  {t.kind === "retention" && (
                    <span className="dp-badge">Already paid</span>
                  )}
                  <p className="dp-type-desc">{t.description}</p>
                </td>
                <td className="dp-num">
                  {t.patient_count === null ? (
                    <span className="dp-unavailable">Not available</span>
                  ) : (
                    formatCount(t.patient_count)
                  )}
                </td>
                <td>
                  <Revenue entry={t} scale={scale} source={source} />
                </td>
                <td>
                  {t.available && t.type_key !== "unclassified" ? (
                    (t.top_service_name ?? "Not recorded")
                  ) : t.available ? (
                    <NotSized reason={NOT_SIZED.noService} />
                  ) : (
                    <span className="dp-unavailable">Not available</span>
                  )}
                </td>
                <td className="dp-chevron" aria-hidden>
                  ›
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Revenue({
  entry: t,
  scale,
  source,
}: {
  entry: TypeEntry;
  scale: number;
  source: "saved" | "file";
}) {
  if (!t.available)
    return (
      <>
        <span className="dp-unavailable">
          {source === "file" ? "Not available from this file" : "Not available for this clinic"}
        </span>
        <p className="dp-small">{unavailableReason(t.type_key, source)}</p>
      </>
    );
  if (t.type_key === "unclassified")
    return (
      <>
        <NotSized reason={NOT_SIZED.unclassified} />
        <p className="dp-small">
          Dormant, but they don&apos;t fit any patient type, so there is no
          revenue figure.
        </p>
      </>
    );
  if (t.kind === "retention")
    return (
      <>
        <span className="dp-money">
          {formatMoney(t.revenue_low_cents ?? 0)}
        </span>{" "}
        already paid, locked in
        <p className="dp-small">Not new revenue, so it isn&apos;t in the total.</p>
      </>
    );
  if (t.revenue_low_cents === null || t.revenue_high_cents === null)
    return <span>Not available</span>;
  const rates =
    t.rate_low !== null && t.rate_high !== null && t.rate_source
      ? `At ${t.rate_source === "measured" ? "your measured" : "an assumed"} return rate of ${formatRateRange(t.rate_low, t.rate_high)}`
      : null;
  return (
    <>
      <span className="dp-money">
        {formatRange(t.revenue_low_cents, t.revenue_high_cents)}
      </span>
      <RangeBar low={t.revenue_low_cents} high={t.revenue_high_cents} max={scale} />
      {rates && <p className="dp-small">{rates}</p>}
    </>
  );
}

