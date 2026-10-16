"use client";

import type { Schemas } from "@clinic/api-client";
import { Badge, Button, Card, Table } from "@clinic/ui";
import { useState, useTransition } from "react";

import { runImport, suggestMapping } from "./actions";

type Suggestion = Schemas["SuggestOut"];
type FieldSpec = Schemas["FieldSpec"];
const ENTITIES = [
  "patient",
  "appointment",
  "transaction",
  "provider",
  "service",
];

export function ImportWizard() {
  const [file, setFile] = useState<File | null>(null);
  const [entity, setEntity] = useState("patient");
  const [sourceSystem, setSourceSystem] = useState("csv");
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [fields, setFields] = useState<Record<string, string | FieldSpec>>({});
  const [result, setResult] = useState<Schemas["ImportOut"] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const form = (extra: Record<string, string> = {}) => {
    const f = new FormData();
    f.set("file", file!);
    f.set("entity_type", entity);
    f.set("source_system", sourceSystem);
    for (const [k, v] of Object.entries(extra)) f.set(k, v);
    return f;
  };

  const analyse = () =>
    startTransition(async () => {
      setError(null);
      setResult(null);
      const { data, error } = await suggestMapping(form());
      if (error || !data) return setError(error ?? "failed");
      setSuggestion(data);
      setFields(data.mapping.fields);
    });

  const submit = () =>
    startTransition(async () => {
      setError(null);
      const mapping = { ...suggestion!.mapping, fields };
      const { data, error } = await runImport(
        form({ mapping: JSON.stringify(mapping), save_mapping: "true" }),
      );
      if (error || !data) return setError(error ?? "failed");
      setResult(data);
    });

  const columnOf = (spec: string | FieldSpec | undefined) =>
    typeof spec === "string" ? spec : (spec?.column ?? "");
  const setColumn = (field: string, column: string) =>
    setFields((prev) => {
      const next = { ...prev };
      const old = prev[field];
      if (!column) delete next[field];
      else next[field] = typeof old === "object" ? { ...old, column } : column;
      return next;
    });

  return (
    <div className="grid gap-4">
      <Card title="1. Choose a file">
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label className="grid gap-1">
            <span className="text-stone-500">What&apos;s in it</span>
            <select
              value={entity}
              onChange={(e) => setEntity(e.target.value)}
              className="rounded border border-stone-300 px-2 py-1.5"
            >
              {ENTITIES.map((e) => (
                <option key={e}>{e}</option>
              ))}
            </select>
          </label>
          <label className="grid gap-1">
            <span className="text-stone-500">Source system</span>
            <input
              value={sourceSystem}
              onChange={(e) => setSourceSystem(e.target.value)}
              className="rounded border border-stone-300 px-2 py-1.5"
            />
          </label>
          <input
            type="file"
            accept=".csv,.xlsx"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <Button onClick={analyse} disabled={!file || pending}>
            Analyse
          </Button>
        </div>
      </Card>

      {suggestion && (
        <Card
          title="2. Confirm the column mapping"
          action={
            <Button onClick={submit} disabled={pending}>
              Import
            </Button>
          }
        >
          <Table
            columns={["Our field", "Column in your file", "Transform"]}
            rows={suggestion.canonical_fields.map((field) => [
              field,
              <select
                key={field}
                value={columnOf(fields[field])}
                onChange={(e) => setColumn(field, e.target.value)}
                className="rounded border border-stone-300 px-2 py-1"
              >
                <option value="">(not in file)</option>
                {suggestion.headers.map((h) => (
                  <option key={h}>{h}</option>
                ))}
              </select>,
              typeof fields[field] === "object"
                ? ((fields[field] as FieldSpec).transform ?? "")
                : "",
            ])}
          />
          <p className="mt-3 text-xs text-stone-500">
            Columns you don&apos;t map are kept on the record as extra
            attributes, so nothing is lost.
          </p>
        </Card>
      )}

      {error && <p className="text-sm text-red-700">{error}</p>}
      {result && (
        <Card title="3. Result">
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge tone="good">{result.stats.created} created</Badge>
            <Badge>{result.stats.updated} updated</Badge>
            <Badge tone={result.stats.errors ? "warn" : "neutral"}>
              {result.stats.errors} errors
            </Badge>
          </div>
          {result.errors.length > 0 && (
            <Table
              columns={["Row", "Problem"]}
              rows={result.errors
                .slice(0, 20)
                .map((e) => [String(e.row), e.error])}
            />
          )}
        </Card>
      )}
    </div>
  );
}
