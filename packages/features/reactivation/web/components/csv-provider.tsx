"use client";
/**
 * Holds the result of an Import CSV analysis in React state only. It is patient data, so it is never put in
 * sessionStorage, localStorage, cookies or the URL: a refresh, closing the tab, leaving Dormant patients,
 * signing out or switching clinic all clear it. The same goes for the file's own bytes, held for the Imported file page.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "@clinic/core/web/auth/provider";

import type { CsvAnalysis, CsvColumns } from "../lib/api-types";
import { formatCount } from "../lib/format";

/** `bytes` is the file itself, kept so the Imported file page can show its rows; null if the browser could not read it. */
export type CsvResult = { data: CsvAnalysis; fileName: string; bytes: ArrayBuffer | null; importedAt: Date };

type Value = {
  result: CsvResult | null;
  setResult: (r: CsvResult) => void;
  clear: () => void;
  columns: CsvColumns | null;
  setColumns: (c: CsvColumns) => void;
  announce: (text: string) => void;
};

const Context = createContext<Value | null>(null);

export function CsvResultProvider({ children }: { children: ReactNode }) {
  const { auth } = useAuth();
  const tenantId = auth.workspace?.id;
  const [result, setResultState] = useState<CsvResult | null>(null);
  const [columns, setColumns] = useState<CsvColumns | null>(null);
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    setResultState(null);
    setColumns(null);
  }, [tenantId]);

  const setResult = useCallback((r: CsvResult) => {
    setResultState(r);
    const dormant = r.data.summary.dormant_count;
    setAnnouncement(
      `Analysis of ${r.fileName} is ready. ${
        typeof dormant === "number" ? `${formatCount(dormant)} dormant patients found.` : ""
      } This data is not saved.`,
    );
  }, []);
  const clear = useCallback(() => setResultState(null), []);
  const value = useMemo(
    () => ({ result, setResult, clear, columns, setColumns, announce: setAnnouncement }),
    [result, setResult, clear, columns],
  );
  return (
    <Context.Provider value={value}>
      {children}
      <p className="dp-visually-hidden" role="status" aria-live="polite" data-testid="csv-live">
        {announcement}
      </p>
    </Context.Provider>
  );
}

export function useCsvResult() {
  const value = useContext(Context);
  if (!value) throw new Error("useCsvResult needs CsvResultProvider");
  return value;
}
