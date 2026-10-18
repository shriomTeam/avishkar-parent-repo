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
import { Heading, Badge, Tabs, Empty, Metric } from "./ui";
import { CallsTable, Transcript } from "./calls-table";
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
          <button
            onClick={() => {
              exportCalls(calls);
              notify("Call history exported");
            }}
          >
            <Download size={16} />
            Export CSV
          </button>
        }
      />
      <section className="panel">
        <div className="filters">
          <input
            aria-label="Search calls"
            placeholder="Search agent or call ID"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <select
            aria-label="Filter call status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">All statuses</option>
            <option>Completed</option>
            <option>Failed</option>
            <option>In progress</option>
          </select>
          <select
            aria-label="Filter agent"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
          >
            <option value="all">All agents</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
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
      </section>
      <p>
        Showing {calls.length} of {all.length} calls · {timezone}
      </p>
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
      <section className="panel">
        <Empty
          title="Call not found"
          description="This call does not exist, or belongs to another workspace."
        />
        <Link className="button" href="/voice-receptionist/calls">
          Back to call history
        </Link>
      </section>
    );
  if (error)
    return (
      <section className="panel">
        <p role="alert">{error}</p>
      </section>
    );
  if (!call)
    return (
      <section className="panel">
        <p role="status">Loading call…</p>
      </section>
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
      <Link className="backlink" href="/voice-receptionist/calls">
        <ArrowLeft size={15} />
        Call history
      </Link>
      <Heading
        title={agentName}
        description={`${call.id} · ${dateLabel(call.started_at, timezone)} · ${timezone}`}
        actions={<Badge>{statusLabel(call.status)}</Badge>}
      />
      <div className="cards">
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
      </div>
      <div className="editor">
        <section className="panel">
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
                <dl className="captured">
                  {call.values.map((v) => (
                    <div key={v.key}>
                      <dt>{v.label ?? v.key}</dt>
                      <dd>{String(v.value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <Empty title="Nothing was captured in this call" />
              ))}
            {tab === "Tool executions" &&
              (call.tool_executions?.length ? (
                call.tool_executions.map((e) => (
                  <div key={e.id}>
                    <div className="panelHead">
                      <h3>{e.tool_name}</h3>
                      <Badge>{e.success ? "Success" : "Failed"}</Badge>
                    </div>
                    <p>
                      Run time {e.duration_ms} ms
                      {e.error ? ` · ${e.error}` : ""}
                    </p>
                    <div className="formtwo">
                      <div>
                        <h3>Input</h3>
                        <pre className="code">
                          {JSON.stringify(e.input, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <h3>Result</h3>
                        <pre className="code">
                          {JSON.stringify(e.output, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <Empty title="No tools were used in this call" />
              ))}
            {tab === "Raw responses" &&
              (eventsError ? (
                <p role="alert">{eventsError}</p>
              ) : events === null ? (
                <p role="status">Loading…</p>
              ) : events.length ? (
                <pre className="code raw-events" tabIndex={0}>
                  {events
                    .map((e) =>
                      JSON.stringify({
                        seq: e.seq,
                        type: e.type,
                        ...e.payload,
                      }),
                    )
                    .join("\n")}
                </pre>
              ) : (
                <Empty
                  title="No raw responses saved"
                  description="Raw model messages are off for this agent."
                />
              ))}
          </div>
        </section>
        <div>
          <section className="panel">
            <h2>Call summary</h2>
            <div className="summarylist spaced">
              <div>
                <span>Agent</span>
                <strong>{agentName}</strong>
              </div>
              <div>
                <span>Source</span>
                <strong>{channelLabel(call.channel)}</strong>
              </div>
              <div>
                <span>Model</span>
                <strong>{call.model}</strong>
              </div>
            </div>
          </section>
          <section className="panel spaced">
            <h2>Audio</h2>
            <p>
              Audio is not recorded. Only the transcript and captured details
              are saved, and only if the agent is set to keep them.
            </p>
          </section>
        </div>
      </div>
    </>
  );
}
