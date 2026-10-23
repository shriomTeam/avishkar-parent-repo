"use client";
import { useState } from "react";
import type { Schemas } from "@clinic/api-client";
import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  Note,
  Panel,
  PanelHead,
  Pagination,
  Dropdown,
  TextField,
  Td,
  Th,
  Tr,
} from "@clinic/ui";
import { useWorkspaceResource } from "./use-workspace-resource";

type Filters = {
  start_date: string;
  end_date: string;
  actor: string;
  action: string;
};
const empty: Filters = { start_date: "", end_date: "", actor: "", action: "" };
const label = (value: string) =>
  value.replaceAll(".", " ").replaceAll("_", " ");

export function AuditLog({
  workspaceId,
  canManage,
  timezone,
}: {
  workspaceId: string;
  canManage: boolean;
  timezone: string;
}) {
  return (
    <AuditHistory
      key={workspaceId}
      workspaceId={workspaceId}
      canManage={canManage}
      timezone={timezone}
    />
  );
}

function AuditHistory({
  workspaceId,
  canManage,
  timezone,
}: {
  workspaceId: string;
  canManage: boolean;
  timezone: string;
}) {
  const [draft, setDraft] = useState<Filters>(empty);
  const [filters, setFilters] = useState<Filters>(empty);
  const [page, setPage] = useState(1);
  const base = `/api/v1/workspaces/${workspaceId}/audit`;
  const params = new URLSearchParams(
    Object.entries(filters).filter(([, value]) => value),
  );
  const url = `${base}?${params}&page=${page}`;
  const resource = useWorkspaceResource<Schemas["AuditPage"]>(url, canManage);
  const options = useWorkspaceResource<Schemas["AuditOptions"]>(
    `${base}/options`,
    canManage,
  );
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const invalid =
    !!draft.start_date && !!draft.end_date && draft.start_date > draft.end_date;
  const changed = JSON.stringify(draft) !== JSON.stringify(filters);
  const set = (field: keyof Filters, value: string) =>
    setDraft((previous) => ({ ...previous, [field]: value }));
  async function download() {
    setDownloading(true);
    setDownloadError("");
    try {
      const response = await fetch(`${base}/export?${params}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok)
        throw new Error(
          "Could not download audit logs. Check your access and retry.",
        );
      const blob = await response.blob();
      const href = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = href;
      anchor.download = `workspace-audit-${filters.start_date || "all"}-${filters.end_date || "dates"}.csv`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    } catch (cause) {
      setDownloadError(
        cause instanceof Error ? cause.message : "Download failed.",
      );
    } finally {
      setDownloading(false);
    }
  }
  return (
    <Panel>
      <PanelHead title="Workspace activity" />
      <p className="-mt-2 mb-6 text-[13px] text-muted">
        Browse 50 events per page. Dates and displayed times use {timezone}.
        Downloads include all events matching the applied filters; leave filters
        empty for the full history.
      </p>
      {!canManage ? (
        <Note>
          Only workspace owners and office managers can view the audit log.
        </Note>
      ) : (
        <>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!invalid) {
                setFilters({ ...draft });
                setPage(1);
              }
            }}
          >
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <TextField
                flush
                label="From date"
                type="date"
                value={draft.start_date}
                max={draft.end_date || "9998-12-31"}
                onChange={(e) => set("start_date", e.target.value)}
              />
              <TextField
                flush
                label="To date"
                type="date"
                value={draft.end_date}
                min={draft.start_date || undefined}
                max="9998-12-31"
                onChange={(e) => set("end_date", e.target.value)}
              />
              <Dropdown
                flush
                label="Actor"
                value={draft.actor}
                onChange={(value) => set("actor", value)}
                options={[
                  { value: "", label: "All actors" },
                  ...(options.data?.actors ?? []),
                ]}
              />
              <Dropdown
                flush
                label="Event"
                value={draft.action}
                onChange={(value) => set("action", value)}
                options={[
                  { value: "", label: "All events" },
                  ...(options.data?.events ?? []).map((value) => ({
                    value,
                    label: label(value),
                  })),
                ]}
              />
            </div>
            {invalid && (
              <p role="alert" className="mt-3 text-sm text-red-700">
                From date must be on or before To date.
              </p>
            )}
            <div className="my-5 flex flex-wrap gap-2">
              <Button type="submit" variant="brand" disabled={invalid}>
                Apply filters
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setDraft(empty);
                  setFilters(empty);
                  setPage(1);
                }}
              >
                Clear filters
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={downloading || changed}
                onClick={download}
              >
                {downloading ? "Downloading…" : "Download CSV"}
              </Button>
            </div>
            {changed && (
              <p className="mb-4 text-sm text-muted">
                Apply your filter changes before downloading.
              </p>
            )}
          </form>
          {options.error && (
            <Alert>
              Actor/event options could not load.{" "}
              <Button variant="outline" onClick={options.retry}>
                Retry filters
              </Button>
            </Alert>
          )}
          {downloadError && <Alert>{downloadError}</Alert>}
          {resource.error ? (
            <Alert>
              {resource.error}{" "}
              <Button variant="outline" onClick={resource.retry}>
                Retry
              </Button>
            </Alert>
          ) : !resource.data ? (
            <p role="status">Loading workspace activity…</p>
          ) : (
            <>
              {!resource.data.items.length ? (
                <EmptyState
                  title="No matching activity"
                  description="Try a different date range or clear the filters."
                />
              ) : (
                <DataTable>
                  <thead>
                    <tr>
                      <Th>Event</Th>
                      <Th>Actor</Th>
                      <Th>Time</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {resource.data.items.map((event) => (
                      <Tr key={event.id}>
                        <Td>{label(event.action)}</Td>
                        <Td>{event.actor}</Td>
                        <Td>
                          {new Date(event.occurred_at).toLocaleString("en-GB", {
                            timeZone: timezone,
                          })}
                        </Td>
                      </Tr>
                    ))}
                  </tbody>
                </DataTable>
              )}
              <Pagination
                page={page}
                pageSize={50}
                total={resource.data.total}
                onPageChange={setPage}
              />
            </>
          )}
        </>
      )}
    </Panel>
  );
}
