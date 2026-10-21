"use client";
import { useEffect, useRef } from "react";

import { fileNotes } from "../lib/messages";
import { formatDateTime } from "../lib/format";
import { settingsInUse } from "../lib/settings";
import { num } from "../lib/summary";
import { ExportReportButton } from "./export-button";
import { IMPORT_PATH } from "./shell-nav";
import { useCsvResult, type CsvResult } from "./csv-provider";
import { Button, ButtonLink, Card, EmptyState, Icon, Notice } from "./kit";
import { QualityPanel } from "./quality-panel";
import { Tiles } from "./tiles";
import { TypesTable } from "./types-table";

/** The one thing that tells the reader these numbers are not the saved ones. */
export function CsvBanner({
  fileName,
  actions,
}: {
  fileName: string;
  actions?: React.ReactNode;
}) {
  return (
    <div data-testid="csv-banner">
      <Notice
        tone="info"
        title={`Showing results from ${fileName}.`}
        action={actions}
      >
        This data is not saved. Refreshing the page clears it.
      </Notice>
    </div>
  );
}

export function CsvResults({
  result,
  canImport,
  timeZone,
  onBack,
}: {
  result: CsvResult;
  canImport: boolean;
  timeZone: string;
  onBack: () => void;
}) {
  const { data, fileName } = result;
  const heading = useRef<HTMLHeadingElement>(null);
  const { clear } = useCsvResult();

  // Move focus to the new results when they appear, so keyboard and screen-reader users land on them.
  useEffect(() => heading.current?.focus(), [result]);

  function back() {
    clear();
    onBack();
  }

  const dormantTypes = data.types;
  return (
    <div className="dp-stack" data-testid="csv-results">
      <div className="dp-head">
        <div>
          <h1 className="dp-title" tabIndex={-1} ref={heading}>
            Overview <span className="dp-from-file">from file</span>
          </h1>
          <p className="dp-sub" data-testid="analysed-from">
            Analysed {formatDateTime(data.as_of, timeZone)} from {fileName}
          </p>
        </div>
        {canImport && (
          <div className="dp-head-actions">
            <ExportReportButton source={{ kind: "file", fileName, data, dormant: num(data.summary, "dormant_count") }} />
          </div>
        )}
      </div>

      <CsvBanner
        fileName={fileName}
        actions={
          <span className="dp-banner-actions">
            {canImport && (
              <ButtonLink variant="secondary" href={IMPORT_PATH} data-testid="csv-another">
                <Icon name="upload" size={16} />
                Import another file
              </ButtonLink>
            )}
            <Button variant="secondary" onClick={back} data-testid="csv-back">
              Back to saved data
            </Button>
          </span>
        }
      />

      <Notice tone="info" title="Return rates are assumed.">
        Measured rates come from past campaigns, which exist only in your saved data, so a file analysis always uses
        the assumed range.
      </Notice>

      <p className="dp-small" data-testid="csv-settings">
        Analysed with {settingsInUse(data.settings_version)}. Nothing about the file was saved.
      </p>

      <div className="dp-file-frame" data-testid="csv-frame">
        <Tiles
          summary={data.summary}
          file={{ rows: data.counts.rows, patients: data.counts.patients, visitDays: data.counts.visit_days }}
        />
        <Card title="Patient types">
          {dormantTypes.length === 0 ? (
            <EmptyState title="No patient types to show">
              Every patient type is switched off. Turn some on in Settings, then import the file again.
            </EmptyState>
          ) : (
            <TypesTable types={dormantTypes} source="file" />
          )}
        </Card>
      </div>
      <QualityPanel quality={data.quality} source="file" extra={fileNotes(data.notes)} />
    </div>
  );
}
