"use client";
import { useRef, useState } from "react";
import { Button } from "@clinic/ui";

import { CsvHelp, TemplateButton } from "./csv-help";
import { CsvImportPanel } from "./csv-import";

/** The first visit to Dormant patients for a clinic with no patient data and no analysis. */
export function Welcome({ canImport }: { canImport: boolean }) {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  return (
    <div className="dp-stack" data-testid="welcome">
      <section className="dp-welcome" aria-labelledby="dp-welcome-title">
        <h1 className="dp-title dp-welcome-title" id="dp-welcome-title">
          Upload your data to find your dormant patients
        </h1>
        <p className="dp-welcome-text">
          Import a CSV export from your booking or billing system. We&apos;ll show you which patients have gone quiet,
          which kinds of patients they are, and what they could be worth if they came back.
        </p>
        <p className="dp-small">Your file is analysed on the spot and is never saved.</p>
        {canImport ? (
          <div className="dp-welcome-actions">
            <Button onClick={() => setOpen(true)} aria-expanded={open} data-testid="import-csv">
              Import CSV
            </Button>
            <TemplateButton />
          </div>
        ) : (
          <p className="dp-welcome-text" data-testid="welcome-no-role">
            The clinic owner or office manager can import the first file. Ask them to open this page.
          </p>
        )}
      </section>
      {open && canImport && (
        <div ref={panel}>
          <CsvImportPanel onDone={() => setOpen(false)} onCancel={() => setOpen(false)} />
        </div>
      )}
      <CsvHelp />
    </div>
  );
}
