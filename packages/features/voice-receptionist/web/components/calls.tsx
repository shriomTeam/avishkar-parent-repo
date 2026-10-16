"use client";
import Link from "next/link";
import { useState } from "react";
import { Download, ArrowLeft } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import { dateLabel, duration, exportCalls } from "../lib/format";
import { Heading, Badge, Tabs, Empty, Metric } from "./ui";
import { CallsTable, Transcript } from "./calls-table";
export function CallHistory() {
  const { state, notify } = useDemo();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [agent, setAgent] = useState("all");
  if (!state) return null;
  const calls = state.calls.filter(
    (c) =>
      [c.id, c.caller, c.phone].some((value) =>
        value.toLowerCase().includes(search.toLowerCase()),
      ) &&
      (status === "all" || status === c.status) &&
      (agent === "all" || agent === c.agentId),
  );
  return (
    <>
      <Heading
        title="Call history"
        description="Every conversation, its outcome and the details behind it."
        actions={
          <button
            onClick={() => {
              exportCalls(calls);
              notify("Filtered sample call history exported");
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
            placeholder="Search caller, phone or call ID"
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
          </select>
          <select
            aria-label="Filter agent"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
          >
            <option value="all">All agents</option>
            {state.agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.draft.name}
              </option>
            ))}
          </select>
        </div>
        <CallsTable calls={calls} timezone={state.workspace.timezone} />
      </section>
      <p>
        Showing {calls.length} sample calls · {state.workspace.timezone}
      </p>
    </>
  );
}
export function CallDetail({ id }: { id: string }) {
  const { state } = useDemo();
  const [tab, setTab] = useState("Transcript");
  const [visual, setVisual] = useState(false);
  if (!state) return null;
  const call = state.calls.find((c) => c.id === id);
  if (!call)
    return (
      <section className="panel">
        <Empty
          title="Call not found"
          description="This call does not exist in the current demo session."
        />
        <Link className="button" href="/voice-receptionist/calls">
          Back to call history
        </Link>
      </section>
    );
  const timing =
    call.latencyMs === null
      ? []
      : ([
          ["Turn detection", 0.33],
          ["STT finalisation", 0.17],
          ["LLM first token", 0.28],
          ["TTS first audio", 0.16],
          ["Transport / other", 0.06],
        ] as [string, number][]);
  return (
    <>
      <Link className="backlink" href="/voice-receptionist/calls">
        <ArrowLeft size={15} />
        Call history
      </Link>
      <Heading
        title={call.caller}
        description={`${call.id} · ${dateLabel(call.startedAt, state.workspace.timezone)} · ${state.workspace.timezone}`}
        actions={<Badge>{call.status}</Badge>}
      />
      <div className="cards">
        <Metric
          label="Duration"
          value={duration(call.durationSeconds)}
          sub={call.phone}
        />
        <Metric label="Outcome" value={call.outcome} sub="Sample call result" />
        <Metric
          label="Response latency"
          value={call.latencyMs === null ? "—" : `${call.latencyMs} ms`}
          sub="Turn end to first audible response"
        />
        <Metric
          label="Call cost"
          value={`$${call.cost.toFixed(2)}`}
          sub="Illustrative sample cost"
        />
      </div>
      <div className="editor">
        <section className="panel">
          <Tabs
            tabs={["Transcript", "Tool executions", "Performance"]}
            value={tab}
            onChange={setTab}
          />
          <div role="tabpanel" aria-label={tab}>
            {tab === "Transcript" &&
              (call.transcript.length ? (
                <Transcript
                  turns={call.transcript}
                  agentName={call.agentName}
                />
              ) : (
                <Empty
                  title="Call ended before a conversation began"
                  description="The connection was lost. No transcript was captured."
                />
              ))}
            {tab === "Tool executions" &&
              (call.toolExecutions.length ? (
                call.toolExecutions.map((execution) => (
                  <div key={execution.idempotencyKey}>
                    <div className="panelHead">
                      <h3>{execution.toolName}</h3>
                      <Badge>{execution.success ? "Success" : "Failed"}</Badge>
                    </div>
                    <p>
                      Execution time {execution.durationMs} ms · Idempotency key{" "}
                      {execution.idempotencyKey}
                    </p>
                    <div className="formtwo">
                      <div>
                        <h3>Input</h3>
                        <pre className="code">
                          {JSON.stringify(execution.input, null, 2)}
                        </pre>
                      </div>
                      <div>
                        <h3>Result</h3>
                        <pre className="code">
                          {JSON.stringify(execution.output, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <Empty title="No tools executed in this call" />
              ))}
            {tab === "Performance" &&
              (call.latencyMs === null ? (
                <Empty
                  title="No response timing available"
                  description="This call ended before the first agent response."
                />
              ) : (
                <>
                  <h3>Response timing</h3>
                  <p>
                    Illustrative stage breakdown of this call’s {call.latencyMs}{" "}
                    ms response latency.
                  </p>
                  {timing.map(([label, ratio]) => (
                    <div key={label}>
                      <div className="rowline">
                        <span>{label}</span>
                        <strong>
                          {Math.round(call.latencyMs! * ratio)} ms
                        </strong>
                      </div>
                      <div className="progress">
                        <i style={{ width: `${ratio * 100}%` }} />
                      </div>
                    </div>
                  ))}
                </>
              ))}
          </div>
        </section>
        <div>
          <section className="panel">
            <h2>Call summary</h2>
            <p>{call.summary}</p>
            <div className="summarylist spaced">
              <div>
                <span>Agent</span>
                <strong>{call.agentName}</strong>
              </div>
              <div>
                <span>Version</span>
                <strong>v{call.version}</strong>
              </div>
              <div>
                <span>Source</span>
                <strong>
                  {call.phone === "Browser test"
                    ? "Simulated browser"
                    : "Sample inbound"}
                </strong>
              </div>
            </div>
          </section>
          <section className="panel spaced">
            <h2>Recording preview</h2>
            {call.recording ? (
              <>
                <p>Visual simulation only. No audio file is attached.</p>
                <div className={`player spaced ${visual ? "is-playing" : ""}`}>
                  <button
                    aria-label={
                      visual
                        ? "Pause visual simulation"
                        : "Start visual simulation"
                    }
                    onClick={() => setVisual(!visual)}
                  >
                    {visual ? "Ⅱ" : "▶"}
                  </button>
                  <div className="wave" aria-hidden="true">
                    {Array.from({ length: 25 }, (_, i) => (
                      <i
                        key={i}
                        style={{ height: `${12 + ((i * 17) % 38)}px` }}
                      />
                    ))}
                  </div>
                </div>
                <small className="spaced">
                  {visual
                    ? "Waveform animation running · No audio"
                    : "Sample waveform · No audio"}
                </small>
              </>
            ) : (
              <p>No recording is available for this call.</p>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
