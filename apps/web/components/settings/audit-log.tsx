"use client";
import type { Schemas } from "@clinic/api-client";
import {
  Alert,
  Button,
  DataTable,
  EmptyState,
  Note,
  Panel,
  PanelHead,
  Td,
  Th,
  Tr,
} from "@clinic/ui";
import { useWorkspaceResource } from "./use-workspace-resource";

export function AuditLog({
  workspaceId,
  canManage,
  timezone,
}: {
  workspaceId: string;
  canManage: boolean;
  timezone: string;
}) {
  const { data, error, retry } = useWorkspaceResource<
    Schemas["WorkspaceAuditOut"][]
  >(`/api/v1/workspaces/${workspaceId}/audit`, canManage);
  return (
    <Panel>
      <PanelHead title="Recent workspace activity" />
      <p className="-mt-2 mb-6 text-[13px] text-muted">
        The latest 100 recorded events. Times are shown in {timezone}.
      </p>
      {!canManage ? (
        <Note>
          Only workspace owners and office managers can view the audit log.
        </Note>
      ) : error ? (
        <Alert>
          {error}{" "}
          <Button variant="outline" onClick={retry}>
            Retry
          </Button>
        </Alert>
      ) : !data ? (
        <p role="status" className="text-sm text-muted">
          Loading workspace activity…
        </p>
      ) : !data.length ? (
        <EmptyState
          title="No recorded activity yet"
          description="Recorded workspace changes will appear here."
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
            {data.map((event) => (
              <Tr key={event.id}>
                <Td>
                  {event.action.replaceAll(".", " ").replaceAll("_", " ")}
                </Td>
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
    </Panel>
  );
}
