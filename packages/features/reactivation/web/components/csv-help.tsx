"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import { browserClient } from "../lib/client";
import { formatCount } from "../lib/format";
import { useCsvResult } from "./csv-provider";
import { CollapsiblePanel, Notice, Skeleton } from "./kit";

/** The column definition lives in the API; this loads it once per visit and shares it. */
export function useCsvColumns() {
  const { auth } = useAuth();
  const { columns, setColumns } = useCsvResult();
  const [failed, setFailed] = useState(false);
  const tenantId = auth.workspace?.id;
  const client = useMemo(
    () => browserClient(auth.csrf_token, tenantId),
    [auth.csrf_token, tenantId],
  );
  const load = useCallback(async () => {
    setFailed(false);
    try {
      const { data } = await client.GET("/features/reactivation/csv-columns");
      if (data) setColumns(data);
      else setFailed(true);
    } catch {
      setFailed(true);
    }
  }, [client, setColumns]);
  useEffect(() => {
    if (!columns) void load();
  }, [columns, load]);
  return { columns, failed, retry: load };
}

export function TemplateButton() {
  const { auth } = useAuth();
  const [error, setError] = useState(false);
  const tenantId = auth.workspace?.id;
  async function download() {
    setError(false);
    try {
      const client = browserClient(auth.csrf_token, tenantId);
      const { data, response } = await client.GET("/features/reactivation/csv-template", {
        parseAs: "blob",
      });
      if (!data || !response.ok) throw new Error("download failed");
      const url = URL.createObjectURL(data as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "dormant-patients-template.csv";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError(true);
    }
  }
  return (
    <>
      <button type="button" className="dp-link-button" onClick={download} data-testid="download-template">
        Download template
      </button>
      {error && (
        <span className="dp-small" role="alert">
          {" "}
          We couldn&apos;t download the template. Please try again.
        </span>
      )}
    </>
  );
}

export function CsvHelp() {
  const { columns, failed, retry } = useCsvColumns();
  return (
    <CollapsiblePanel title="What should my file look like?" testId="csv-help">
      {failed ? (
        <Notice
          tone="error"
          title="We couldn't load the file guide."
          action={
            <button type="button" className="dp-link-button" onClick={retry}>
              Try again
            </button>
          }
        >
          You can still download the template.
        </Notice>
      ) : !columns ? (
        <div role="status" aria-label="Loading the file guide">
          <Skeleton height={14} />
          <div style={{ marginTop: 8 }}>
            <Skeleton width="70%" height={14} />
          </div>
        </div>
      ) : (
        <>
          <ul className="dp-guide-notes">
            {columns.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
            <li>
              Files can be up to {Math.round(columns.limits.max_bytes / (1024 * 1024))} MB, with up to{" "}
              {formatCount(columns.limits.max_rows)} rows and {formatCount(columns.limits.max_patients)} patients.
            </li>
          </ul>
          <div className="dp-table-wrap">
            <table className="dp-table dp-guide" data-testid="csv-columns">
              <caption className="dp-visually-hidden">Columns in the file</caption>
              <thead>
                <tr>
                  <th scope="col">Column</th>
                  <th scope="col">What to put in it</th>
                  <th scope="col">If it&apos;s missing</th>
                </tr>
              </thead>
              <tbody>
                {columns.columns.map((c) => (
                  <tr key={c.name}>
                    <th scope="row" className="dp-guide-name">
                      <code>{c.name}</code>
                      {c.required && <span className="dp-badge">Required</span>}
                    </th>
                    <td>
                      {c.description}
                      {c.values.length > 0 && (
                        <p className="dp-small">Allowed: {c.values.join(", ")}</p>
                      )}
                      <p className="dp-small">
                        Example: <code>{c.example}</code>
                      </p>
                    </td>
                    <td>{c.required ? "The file is rejected." : c.if_missing}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </CollapsiblePanel>
  );
}
