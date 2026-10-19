"use client";
import { useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import { formatCount } from "../lib/format";
import { uploadCsv, type CsvFailure } from "../lib/csv-upload";
import { TemplateButton, useCsvColumns } from "./csv-help";
import { useCsvResult } from "./csv-provider";
import { Button, Card, Icon, Notice, ProgressBar } from "./kit";

type Phase =
  | { kind: "idle" }
  | { kind: "busy"; file: string; stage: "uploading" | "analysing"; pct: number }
  | { kind: "error"; file: string; failure: Pick<CsvFailure, "message" | "total" | "errors"> };

const mb = (bytes: number) => Math.round(bytes / (1024 * 1024));

/** Pick or drop a CSV file; it is analysed on the spot and the result goes to the in-memory provider. */
export function CsvImportPanel({ onDone, onCancel }: { onDone: () => void; onCancel?: () => void }) {
  const { auth } = useAuth();
  const { setResult } = useCsvResult();
  const { columns } = useCsvColumns();
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const drop = useRef<HTMLDivElement>(null);
  const errorBox = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const tenantId = auth.workspace?.id;
  const maxBytes = columns?.limits.max_bytes;

  const focusChoose = () => drop.current?.querySelector("button")?.focus();
  useEffect(focusChoose, []);
  useEffect(() => {
    if (phase.kind === "error") errorBox.current?.focus();
  }, [phase]);
  useEffect(() => () => abort.current?.abort(), []);

  const problem = useMemo(
    () => (file: File): string | null => {
      if (!/\.csv$/i.test(file.name))
        return "That isn't a .csv file. In Excel or Sheets, choose Save As and pick CSV (UTF-8).";
      if (file.size === 0) return "That file is empty.";
      if (maxBytes && file.size > maxBytes)
        return `That file is ${mb(file.size)} MB. The limit is ${mb(maxBytes)} MB.`;
      return null;
    },
    [maxBytes],
  );

  async function start(file: File) {
    const bad = problem(file);
    if (bad) {
      setPhase({ kind: "error", file: file.name, failure: { message: bad, total: 0, errors: [] } });
      return;
    }
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setPhase({ kind: "busy", file: file.name, stage: "uploading", pct: 0 });
    const outcome = await uploadCsv(file, {
      csrfToken: auth.csrf_token,
      tenantId,
      signal: controller.signal,
      onProgress: (pct) =>
        setPhase((p) => (p.kind === "busy" && p.stage === "uploading" ? { ...p, pct } : p)),
      onUploaded: () =>
        setPhase((p) => (p.kind === "busy" ? { ...p, stage: "analysing", pct: 100 } : p)),
    });
    if (controller.signal.aborted) return;
    if (outcome.ok) {
      setResult({ data: outcome.data, fileName: file.name });
      setPhase({ kind: "idle" });
      onDone();
    } else if (!outcome.cancelled) {
      setPhase({ kind: "error", file: file.name, failure: outcome.failure });
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (phase.kind === "busy") return;
    const files = [...e.dataTransfer.files];
    if (files.length !== 1) {
      setPhase({
        kind: "error",
        file: "",
        failure: { message: "Drop one file at a time.", total: 0, errors: [] },
      });
      return;
    }
    const [only] = files;
    if (only) void start(only);
  }

  function cancel() {
    abort.current?.abort();
    setPhase({ kind: "idle" });
    requestAnimationFrame(focusChoose);
  }

  const busy = phase.kind === "busy";
  return (
    <Card>
      <div className="dp-import" data-testid="csv-panel">
        <div className="dp-import-head">
          <h2 className="dp-import-title">Import a CSV file</h2>
          {onCancel && !busy && (
            <button type="button" className="dp-link-button" onClick={onCancel}>
              Close
            </button>
          )}
        </div>
        <p className="dp-sub">
          Your file is analysed on the spot and is never saved. The results show only in this tab and clear when you
          refresh. Return rates are assumed, because measured rates come from past campaigns in your saved data.
        </p>

        <div
          ref={drop}
          className="dp-drop"
          data-dragging={dragging || undefined}
          data-busy={busy || undefined}
          data-testid="csv-dropzone"
          role="group"
          aria-label="Choose a CSV file or drop it here"
          onDragOver={(e) => {
            e.preventDefault();
            if (!busy) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input
            ref={input}
            type="file"
            accept=".csv,text/csv"
            className="dp-visually-hidden"
            tabIndex={-1}
            aria-hidden
            data-testid="csv-file-input"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void start(file);
            }}
          />
          {busy ? (
            <div className="dp-drop-busy" data-testid="csv-progress">
              <p className="dp-drop-file">{phase.file}</p>
              {phase.stage === "uploading" ? (
                <>
                  <ProgressBar value={phase.pct} label="Uploading file" />
                  <p className="dp-hint" role="status">
                    Uploading… {phase.pct}%
                  </p>
                </>
              ) : (
                <>
                  <div className="dp-bar dp-bar-indeterminate" role="progressbar" aria-label="Analysing patients">
                    <span />
                  </div>
                  <p className="dp-hint" role="status">
                    Analysing your patients. Large files can take up to a minute.
                  </p>
                </>
              )}
              <Button variant="secondary" onClick={cancel}>
                Cancel
              </Button>
            </div>
          ) : (
            <>
              <span className="dp-drop-icon">
                <Icon name="file" size={22} />
              </span>
              <p className="dp-drop-text">Drag a .csv file here, or</p>
              <Button onClick={() => input.current?.click()} data-testid="csv-choose">
                <Icon name="upload" size={16} />
                Choose a file
              </Button>
              <p className="dp-small">
                UTF-8 CSV, one row per line sold
                {maxBytes ? `, up to ${mb(maxBytes)} MB` : ""}.{" "}
                {columns ? `Up to ${formatCount(columns.limits.max_rows)} rows.` : ""}
              </p>
            </>
          )}
        </div>

        {phase.kind === "error" && (
          <div ref={errorBox} tabIndex={-1} className="dp-import-error" data-testid="csv-errors">
            <Notice tone="error" title={phase.file ? `We couldn't analyse ${phase.file}.` : "We couldn't analyse that."}>
              {phase.failure.message}
            </Notice>
            {phase.failure.errors.length > 0 && (
              <div className="dp-table-wrap">
                <table className="dp-table dp-errors">
                  <caption className="dp-errors-caption">
                    {phase.failure.total > phase.failure.errors.length
                      ? `Showing the first ${phase.failure.errors.length} of ${formatCount(phase.failure.total)} problems.`
                      : `${formatCount(phase.failure.total)} ${phase.failure.total === 1 ? "problem" : "problems"}.`}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col" className="dp-num">
                        Row
                      </th>
                      <th scope="col">Column</th>
                      <th scope="col">Problem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {phase.failure.errors.map((e, i) => (
                      <tr key={i} data-testid="csv-error-row">
                        <td className="dp-num">{e.row}</td>
                        <td>
                          <code>{e.column}</code>
                        </td>
                        <td>{e.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="dp-small">Fix the file and choose it again. Nothing was analysed or saved.</p>
          </div>
        )}
        <p className="dp-small">
          Need an example? <TemplateButton />
        </p>
      </div>
    </Card>
  );
}
