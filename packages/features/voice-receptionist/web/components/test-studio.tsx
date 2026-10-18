"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Mic } from "lucide-react";
import { useVoice } from "../lib/voice/provider";
import { useTestCall } from "../lib/voice/use-test-call";
import { Heading, Select, Badge, Empty, FormError } from "./ui";
import { VoiceBoundary } from "./voice-boundary";

const clock = (s: number) =>
  `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;

export function TestStudio() {
  return (
    <VoiceBoundary>
      <Studio />
    </VoiceBoundary>
  );
}

function Studio() {
  const { agents, api, reloadCalls } = useVoice();
  const params = useSearchParams();
  const requested = params.get("agent");
  const [selected, setSelected] = useState(
    agents.find((a) => a.id === requested)?.id ??
      agents.find((a) => a.is_active)?.id ??
      agents[0]?.id ??
      "",
  );
  const call = useTestCall(api, reloadCalls);
  const agent = agents.find((a) => a.id === selected);
  const fields = agent?.fields ?? [];
  const finished = call.state === "ended" && call.callId;

  return (
    <>
      <Heading
        title="Test studio"
        description="Try your agent before callers do. You speak, the agent answers out loud."
        actions={
          agent && (
            <Link
              className="button"
              href={`/voice-receptionist/agents/${agent.id}`}
            >
              Edit agent
            </Link>
          )
        }
      />
      {agents.length === 0 ? (
        <section className="panel">
          <Empty
            title="Create an agent first"
            description="You need at least one agent to take a test call."
          />
          <Link className="button" href="/voice-receptionist/agents">
            Go to agents
          </Link>
        </section>
      ) : (
        <div className="two">
          <section className="panel">
            <div className="panelHead">
              <h2>Browser call</h2>
              <Badge>
                {call.state === "live"
                  ? "Live"
                  : call.state === "connecting"
                    ? "Connecting"
                    : "Ready"}
              </Badge>
            </div>
            <Select
              label="Agent"
              value={selected}
              disabled={call.busy}
              onChange={(e) => setSelected(e.target.value)}
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </Select>
            <div className="testcenter">
              <div
                className={`orb ${call.state === "live" ? "live" : ""}`}
                style={{
                  transform:
                    call.state === "live"
                      ? `scale(${1 + call.level * 0.18})`
                      : undefined,
                }}
              >
                <Mic size={32} />
              </div>
              <h2>
                {call.state === "live"
                  ? `${agent?.voice ?? "The agent"} is listening · ${clock(call.seconds)}`
                  : call.state === "connecting"
                    ? "Connecting…"
                    : finished
                      ? "Test call completed"
                      : "Ready when you are"}
              </h2>
              <p>Use headphones so the agent does not hear itself.</p>
              <button
                className={`${call.busy ? "danger" : "primary"} spaced`}
                disabled={
                  !agent ||
                  (!call.busy && !agent.is_active) ||
                  call.state === "connecting"
                }
                onClick={() =>
                  call.busy ? call.hangup() : agent && call.start(agent)
                }
              >
                {call.busy
                  ? "End call"
                  : finished || call.state === "error"
                    ? "Call again"
                    : "Start test call"}
              </button>
              {agent && !agent.is_active && (
                <small>
                  This agent is disabled. Turn it on in its settings to call it.
                </small>
              )}
            </div>
            <FormError message={call.error} />
            {finished && (
              <div className="note">
                <strong>Test complete</strong>
                <p>
                  {call.reason} The call was saved with its transcript and
                  captured details.
                </p>
                <Link
                  className="button spaced"
                  href={`/voice-receptionist/calls/${call.callId}`}
                >
                  View saved call
                </Link>
              </div>
            )}
            <small>
              Test calls use the saved agent and appear in call history.
            </small>
          </section>
          <section className="panel">
            <div className="panelHead">
              <h2>Conversation</h2>
              <span className="pill">
                {call.state === "live" ? "Live transcript" : "Transcript"}
              </span>
            </div>
            {call.lines.length === 0 ? (
              <Empty
                title="Your conversation appears here"
                description="Start a test call to see the dialogue as it happens."
              />
            ) : (
              <div aria-live="polite" data-testid="live-transcript">
                {call.lines.map((line, i) => (
                  <div
                    key={i}
                    className={`chat ${line.speaker === "agent" ? "agent" : ""}`}
                  >
                    <div
                      className={`avatar ${line.speaker === "caller" ? "dark" : ""}`}
                    >
                      {line.speaker === "agent" ? (agent?.name[0] ?? "A") : "Y"}
                    </div>
                    <div className="bubble">
                      <strong>
                        {line.speaker === "agent" ? agent?.name : "You"}
                      </strong>
                      {line.text}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {call.toolRuns.length > 0 && (
              <>
                <h3>Tool activity</h3>
                <div data-testid="tool-activity">
                  {call.toolRuns.map((run, i) => (
                    <div className="rowline" key={i}>
                      <span>
                        {run.name}
                        {run.durationMs !== undefined
                          ? ` · ${run.durationMs} ms`
                          : ""}
                      </span>
                      <Badge>
                        {run.status === "running"
                          ? "Running"
                          : run.status === "ok"
                            ? "Success"
                            : "Failed"}
                      </Badge>
                    </div>
                  ))}
                </div>
              </>
            )}
            {fields.length > 0 &&
              (call.state !== "idle" ||
                Object.keys(call.values).length > 0) && (
                <>
                  <h3>Captured details</h3>
                  <dl className="captured" data-testid="captured-fields">
                    {fields.map((f) => (
                      <div key={f.key}>
                        <dt>
                          {f.label}
                          {f.required ? " *" : ""}
                        </dt>
                        <dd>
                          {call.values[f.key] === undefined ? (
                            <span className="muted">not yet</span>
                          ) : (
                            String(call.values[f.key])
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}
          </section>
        </div>
      )}
    </>
  );
}
