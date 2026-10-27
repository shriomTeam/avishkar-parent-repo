"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Download, ArrowLeft } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import {
  ApiError,
  type CallDetail as Detail,
  type InboundApi,
} from "../lib/inbound/api";
import {
  callDuration,
  channelLabel,
  dateLabel,
  duration,
  exportCalls,
  reasonLabel,
  statusLabel,
} from "../lib/format";
import {
  Alert,
  backLinkStyles,
  Button,
  buttonStyles,
  CodeBlock,
  DetailList,
  H2,
  H3,
  Input,
  Dropdown,
  Muted,
  Panel,
  PanelHead,
  SidebarLayout,
  StatGrid,
  SummaryList,
  TwoColumns,
} from "@clinic/ui";
import { Heading, Badge, Tabs, Empty, Metric } from "./ui";
import { CallsTable, Transcript } from "./calls-table";
import { RecordingPlayer } from "./recording-player";
import { VoiceBoundary } from "./voice-boundary";

export function CallHistory() {
  return (
    <VoiceBoundary>
      <History />
    </VoiceBoundary>
  );
}

function History() {
  const { agents, calls: all } = useVoice();
  const { state, notify } = useDemo();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [agent, setAgent] = useState("all");
  const timezone = state?.workspace.timezone || "UTC";
  const calls = all.filter(
    (c) =>
      [c.id, c.agent_name ?? ""].some((value) =>
        value.toLowerCase().includes(search.toLowerCase()),
      ) &&
      (status === "all" || status === statusLabel(c.status)) &&
      (agent === "all" || agent === c.agent_id),
  );
  return (
    <>
      <Heading
        title="Call history"
        description="Every conversation, how it ended and the details it captured."
        actions={
          <Button
            variant="outline"
            onClick={() => {
              exportCalls(calls);
              notify("Call history exported");
            }}
          >
            <Download size={16} />
            Export CSV
          </Button>
        }
      />
      <Panel>
        <div className="mb-5 flex items-center gap-3 max-app:flex-wrap">
          <Input
            inline
            className="flex-1 max-app:basis-full"
            aria-label="Search calls"
            placeholder="Search agent or call ID"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <Dropdown
            inline
            hideLabel
            className="max-w-[190px] max-app:max-w-full max-app:flex-1"
            label="Filter call status"
            value={status}
            onChange={setStatus}
            options={[
              { value: "all", label: "All statuses" },
              { value: "Completed", label: "Completed" },
              { value: "Failed", label: "Failed" },
              { value: "In progress", label: "In progress" },
            ]}
          />
          <Dropdown
            inline
            hideLabel
            className="max-w-[190px] max-app:max-w-full max-app:flex-1"
            label="Filter agent"
            value={agent}
            onChange={setAgent}
            options={[
              { value: "all", label: "All agents" },
              ...agents.map((a) => ({ value: a.id, label: a.name })),
            ]}
          />
        </div>
        <CallsTable
          calls={calls}
          timezone={timezone}
          empty={
            all.length === 0
              ? {
                  title: "No calls yet",
                  description:
                    "Take a test call in Test studio and it will appear here.",
                }
              : undefined
          }
        />
      </Panel>
      <Muted>
        Showing {calls.length} of {all.length} calls · {timezone}
      </Muted>
    </>
  );
}

export function CallDetail({ id }: { id: string }) {
  return (
    <VoiceBoundary>
      <DetailLoader id={id} />
    </VoiceBoundary>
  );
}

function DetailLoader({ id }: { id: string }) {
  const { api } = useVoice();
  const [call, setCall] = useState<Detail | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    api
      .getCall(id)
      .then((c) => live && setCall(c))
      .catch((e) => {
        if (!live) return;
        if (e instanceof ApiError && (e.status === 404 || e.status === 422))
          setMissing(true);
        else
          setError(
            e instanceof ApiError ? e.message : "Could not load this call.",
          );
      });
    return () => {
      live = false;
    };
  }, [api, id]);

  if (missing)
    return (
      <Panel>
        <Empty
          title="Call not found"
          description="This call does not exist, or belongs to another workspace."
        />
        <Link
          className={buttonStyles("outline")}
          href="/voice-receptionist/calls"
        >
          Back to call history
        </Link>
      </Panel>
    );
  if (error)
    return (
      <Panel>
        <Alert>{error}</Alert>
      </Panel>
    );
  if (!call)
    return (
      <Panel>
        <Muted role="status">Loading call…</Muted>
      </Panel>
    );
  return <DetailView call={call} api={api} />;
}

function DetailView({ call, api }: { call: Detail; api: InboundApi }) {
  const { state } = useDemo();
  const [tab, setTab] = useState("Transcript");
  // Raw model messages can run to thousands of rows on a long call, so they load only when that tab is opened.
  const [events, setEvents] = useState<Detail["events"] | null>(null);
  const [eventsError, setEventsError] = useState("");
  useEffect(() => {
    if (tab !== "Raw responses" || events !== null) return;
    let live = true;
    api
      .getCall(call.id, true)
      .then((c) => live && setEvents(c.events))
      .catch(() => live && setEventsError("Could not load the raw responses."));
    return () => {
      live = false;
    };
  }, [tab, events, api, call.id]);
  const timezone = state?.workspace.timezone || "UTC";
  const tokens = (call.usage as { total_token_count?: number } | undefined)
    ?.total_token_count;
  const agentName = call.agent_name || "Deleted agent";
  const turns = call.turns.map((t) => ({
    speaker: t.speaker === "agent" ? ("Agent" as const) : ("Caller" as const),
    time:
      duration(Math.round(t.offset_ms / 1000)) +
      (t.interrupted ? " · interrupted" : ""),
    text: t.text,
  }));
  return (
    <>
      <Link className={backLinkStyles} href="/voice-receptionist/calls">
        <ArrowLeft size={15} />
        Call history
      </Link>
      <Heading
        title={agentName}
        description={`${call.id} · ${dateLabel(call.started_at, timezone)} · ${timezone}`}
        actions={<Badge>{statusLabel(call.status)}</Badge>}
      />
      <StatGrid>
        <Metric
          label="Duration"
          value={callDuration(call.duration_seconds)}
          sub={channelLabel(call.channel)}
        />
        <Metric
          label="How it ended"
          value={reasonLabel(call.end_reason)}
          sub="Reported by the call"
        />
        <Metric
          label="Details captured"
          value={String(call.captured_count ?? 0)}
          sub="Saved with this call"
        />
        <Metric
          label="Model usage"
          value={tokens === undefined ? "—" : String(tokens)}
          sub="Tokens reported by the model"
        />
      </StatGrid>
      <SidebarLayout>
        <Panel>
          <RecordingPlayer
            callId={call.id}
            status={call.recording_status}
            api={api}
          />
          <Tabs
            tabs={[
              "Transcript",
              "Captured details",
              "Tool executions",
              "Raw responses",
            ]}
            value={tab}
            onChange={setTab}
          />
          <div role="tabpanel" aria-label={tab}>
            {tab === "Transcript" &&
              (turns.length ? (
                <Transcript turns={turns} agentName={agentName} />
              ) : (
                <Empty
                  title="No transcript for this call"
                  description="Transcripts are off for this agent, or the call ended before anyone spoke."
                />
              ))}
            {tab === "Captured details" &&
              (call.values.length ? (
                <DetailList
                  items={call.values.map((v) => [
                    v.label ?? v.key,
                    String(v.value),
                  ])}
                />
              ) : (
                <Empty title="Nothing was captured in this call" />
              ))}
            {tab === "Tool executions" &&
              (call.tool_executions?.length ? (
                call.tool_executions.map((e) => (
                  <div key={e.id}>
                    <PanelHead
                      title={e.tool_name}
                      level="h3"
                      action={<Badge>{e.success ? "Success" : "Failed"}</Badge>}
                    />
                    <Muted>
                      Run time {e.duration_ms} ms
                      {e.error ? ` · ${e.error}` : ""}
                    </Muted>
                    <TwoColumns>
                      <div>
                        <H3>Input</H3>
                        <CodeBlock>
                          {JSON.stringify(e.input, null, 2)}
                        </CodeBlock>
                      </div>
                      <div>
                        <H3>Result</H3>
                        <CodeBlock>
                          {JSON.stringify(e.output, null, 2)}
                        </CodeBlock>
                      </div>
                    </TwoColumns>
                  </div>
                ))
              ) : (
                <Empty title="No tools were used in this call" />
              ))}
            {tab === "Raw responses" &&
              (eventsError ? (
                <Alert>{eventsError}</Alert>
              ) : events === null ? (
                <Muted role="status">Loading…</Muted>
              ) : events.length ? (
                <CodeBlock
                  data-testid="raw-events"
                  className="max-h-[260px] overflow-auto rounded-lg bg-[#f6f5f8] p-3 text-[12px]"
                  tabIndex={0}
                >
                  {events
                    .map((e) =>
                      JSON.stringify({
                        seq: e.seq,
                        type: e.type,
                        ...e.payload,
                      }),
                    )
                    .join("\n")}
                </CodeBlock>
              ) : (
                <Empty
                  title="No raw responses saved"
                  description="Raw model messages are off for this agent."
                />
              ))}
          </div>
        </Panel>
        <div>
          <Panel>
            <H2>Call summary</H2>
            <SummaryList
              className="mt-5"
              items={[
                ["Agent", agentName],
                ["Source", channelLabel(call.channel)],
                ["Model", call.model],
              ]}
            />
          </Panel>
          <Panel className="mt-5">
            <H2>Audio</H2>
            <Muted>
              {call.recording_status === "saved"
                ? "This call was recorded. Press Play recording above the transcript to listen."
                : call.recording_status === "failed"
                  ? "This call was set to be recorded, but the audio could not be saved."
                  : "This call was not recorded. Turn on Record the call in the agent’s Data & privacy settings to keep the audio of future calls."}
            </Muted>
          </Panel>
        </div>
      </SidebarLayout>
    </>
  );
}
