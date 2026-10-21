"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import { indexFor, readRecord, readRecords } from "../lib/csv-read";
import { formatCount, formatDateTime } from "../lib/format";
import { canRunRole } from "../lib/roles";
import { useCsvResult } from "./csv-provider";
import { Button, ButtonLink, Card, EmptyState, Notice, PageHead } from "./kit";
import { IMPORT_PATH } from "./shell-nav";

const SIZES = [25, 50, 100];

/** Shown to a role that cannot import, so there is never a file to show. */
export function FileRefused() {
  return (
    <div className="dp-stack" data-testid="file-refused">
      <PageHead title="Imported file" />
      <Card>
        <EmptyState title="No file to show" icon="table">
          Only an owner or office manager can import files.
        </EmptyState>
      </Card>
    </div>
  );
}

/** The rows of the file imported in this tab, read in the browser from the same file; nothing is fetched. */
export function FileViewer() {
  const { auth } = useAuth();
  const { result } = useCsvResult();
  const tenantId = auth.workspace?.id;
  const role = auth.memberships.find((m) => m.workspace_id === tenantId)?.role;
  const timeZone = auth.workspace?.timezone ?? "America/New_York";
  if (!canRunRole(role)) return <FileRefused />;

  if (!result)
    return (
      <div className="dp-stack" data-testid="file-viewer">
        <PageHead title="Imported file" />
        <Card>
          <EmptyState
            title="No file imported yet"
            icon="table"
            testId="file-empty"
            action={
              <ButtonLink href={IMPORT_PATH} data-testid="file-import-link">
                Import data
              </ButtonLink>
            }
          >
            Import a CSV file and its rows will show here.
          </EmptyState>
        </Card>
      </div>
    );

  return (
    <div className="dp-stack" data-testid="file-viewer">
      <div className="dp-head">
        <div>
          <h1 className="dp-title">
            Imported file <span className="dp-from-file">from file</span>
          </h1>
          <FileMeta name={result.fileName} importedAt={formatDateTime(result.importedAt.toISOString(), timeZone)} bytes={result.bytes} />
        </div>
      </div>
      <p className="dp-small" data-testid="file-privacy">
        Shown only in this tab. Nothing is saved or sent. Refreshing the page clears it.
      </p>
      {result.bytes ? (
        <FileTable bytes={result.bytes} fileName={result.fileName} />
      ) : (
        <Notice tone="error">
          We couldn&apos;t keep a copy of this file to show. Import it again to view its rows.
        </Notice>
      )}
    </div>
  );
}

function FileMeta({ name, importedAt, bytes }: { name: string; importedAt: string; bytes: ArrayBuffer | null }) {
  // The row count needs the index, which is built once and shared with the table below.
  const rows = useRowCount(bytes);
  return (
    <p className="dp-sub" data-testid="file-meta">
      {name}
      {rows !== null && ` · ${formatCount(rows)} rows`} · imported {importedAt}
    </p>
  );
}

function useRowCount(bytes: ArrayBuffer | null) {
  const [rows, setRows] = useState<number | null>(null);
  useEffect(() => {
    if (!bytes) return;
    const timer = setTimeout(() => setRows(Math.max(0, indexFor(bytes).count - 1)), 0);
    return () => clearTimeout(timer);
  }, [bytes]);
  return rows;
}

function FileTable({ bytes, fileName }: { bytes: ArrayBuffer; fileName: string }) {
  const [ready, setReady] = useState(false);
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(50);
  const region = useRef<HTMLDivElement>(null);

  // Index the file after the first paint so "Preparing the file…" shows; the index is cached per buffer.
  useEffect(() => {
    setReady(false);
    const timer = setTimeout(() => {
      indexFor(bytes);
      setReady(true);
    }, 0);
    return () => clearTimeout(timer);
  }, [bytes]);

  const view = useMemo(() => {
    if (!ready) return null;
    const index = indexFor(bytes);
    const raw = new Uint8Array(bytes);
    const total = Math.max(0, index.count - 1);
    const pages = Math.max(1, Math.ceil(total / size));
    const at = Math.min(page, pages - 1);
    const first = 1 + at * size;
    const header = readRecord(raw, index, 0);
    const rows = readRecords(raw, index, first, first + size);
    const lines = Array.from(rows, (_, i) => index.lines[first + i] as number);
    return { total, pages, at, header, rows, lines };
  }, [ready, bytes, page, size]);

  useEffect(() => {
    if (region.current) region.current.scrollTop = 0;
  }, [view?.at, size]);

  if (!view)
    return (
      <p className="dp-small" role="status" data-testid="file-preparing">
        Preparing the file…
      </p>
    );

  const { total, pages, at, header, rows, lines } = view;
  const from = total === 0 ? 0 : at * size + 1;
  const to = Math.min(total, at * size + size);
  const go = (next: number) => setPage(Math.max(0, Math.min(pages - 1, next)));
  const pagerButton = (label: string, testId: string, target: number, off: boolean) => (
    <Button
      variant="secondary"
      aria-disabled={off || undefined}
      onClick={() => {
        if (!off) go(target);
      }}
      data-testid={testId}
    >
      {label}
    </Button>
  );

  return (
    <div className="dp-file-frame" data-plain="" data-testid="file-table-frame">
      <Card>
        <div
          ref={region}
          className="dp-grid-scroll"
          role="region"
          aria-label={`Rows of ${fileName}`}
          tabIndex={0}
          data-testid="file-region"
        >
          <table className="dp-grid" data-testid="file-table">
            <caption className="dp-visually-hidden">Rows of {fileName}</caption>
            <thead>
              <tr>
                <th scope="col">Row</th>
                {header.map((name, i) => (
                  <th scope="col" key={i}>
                    {name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((cells, r) => (
                <tr key={lines[r]} data-testid="file-row">
                  <th scope="row">{lines[r]}</th>
                  {header.map((_, c) => (
                    <td key={c}>{cells[c] ?? ""}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="dp-pager">
          <p className="dp-small" role="status" data-testid="file-range">
            Showing {formatCount(from)} to {formatCount(to)} of {formatCount(total)} rows
          </p>
          <label className="dp-field dp-field-inline">
            <span>Rows per page</span>
            <select
              value={size}
              onChange={(e) => {
                const next = Number(e.target.value);
                setPage(Math.floor((at * size) / next));
                setSize(next);
              }}
              data-testid="file-size"
            >
              {SIZES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <div className="dp-pager-buttons">
            {pagerButton("First", "file-first", 0, at === 0)}
            {pagerButton("Previous", "file-prev", at - 1, at === 0)}
            <span className="dp-pager-page" data-testid="file-page">
              Page {formatCount(at + 1)} of {formatCount(pages)}
            </span>
            {pagerButton("Next", "file-next", at + 1, at >= pages - 1)}
            {pagerButton("Last", "file-last", pages - 1, at >= pages - 1)}
          </div>
        </div>
      </Card>
    </div>
  );
}
