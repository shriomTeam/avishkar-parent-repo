"use client";
import { initials } from "@clinic/core/web/auth/types";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Mic } from "lucide-react";
import { useVoice } from "../lib/voice/provider";
import { useTestCall } from "../lib/voice/use-test-call";
import {
  Button,
  buttonStyles,
  ChatMessage,
  DetailList,
  FooterRow,
  H2,
  H3,
  Muted,
  Note,
  Panel,
  PanelHead,
  Pill,
  WideSplit,
} from "@clinic/ui";
import { Heading, Dropdown, Badge, Empty, FormError } from "./ui";
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
              className={buttonStyles("outline")}
              href={`/voice-receptionist/agents/${agent.id}`}
            >
              Edit agent
            </Link>
          )
        }
      />
      {agents.length === 0 ? (
        <Panel>
          <Empty
            title="Create an agent first"
            description="You need at least one agent to take a test call."
          />
          <Link
            className={buttonStyles("outline")}
            href="/voice-receptionist/agents"
          >
            Go to agents
          </Link>
        </Panel>
      ) : (
        <WideSplit>
          <Panel>
            <PanelHead
              title="Browser call"
              action={
                <Badge>
                  {call.state === "live"
                    ? "Live"
                    : call.state === "connecting"
                      ? "Connecting"
                      : "Ready"}
                </Badge>
              }
            />
            <Dropdown
              label="Agent"
              value={selected}
              disabled={call.busy}
              onChange={setSelected}
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
            />
            <div className="px-[25px] py-[42px] text-center">
              <div
                className={`mx-auto my-[25px] grid size-[110px] place-items-center rounded-full border-[13px] border-[#f4ffed] bg-brand-soft text-brand-ink ${call.state === "live" ? "animate-pulse-ring" : ""}`}
                style={{
                  transform:
                    call.state === "live"
                      ? `scale(${1 + call.level * 0.18})`
                      : undefined,
                }}
              >
                <Mic size={32} />
              </div>
              <H2>
                {call.state === "live"
                  ? `${agent?.voice ?? "The agent"} is listening · ${clock(call.seconds)}`
                  : call.state === "connecting"
                    ? "Connecting…"
                    : finished
                      ? "Test call completed"
                      : "Ready when you are"}
              </H2>
              <Muted>Use headphones so the agent does not hear itself.</Muted>
              <Button
                variant={call.busy ? "dangerOutline" : "brand"}
                className="mt-5"
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
              </Button>
              {agent && !agent.is_active && (
                <small className="block text-[12px] text-muted">
                  This agent is disabled. Turn it on in its settings to call it.
                </small>
              )}
            </div>
            <FormError message={call.error} />
            {finished && (
              <Note>
                <strong>Test complete</strong>
                <p>
                  {call.reason} The call was saved with its transcript and
                  captured details.
                </p>
                <Link
                  className={buttonStyles("outline", { className: "mt-5" })}
                  href={`/voice-receptionist/calls/${call.callId}`}
                >
                  View saved call
                </Link>
              </Note>
            )}
            <small className="block text-[12px] text-muted">
              Test calls use the saved agent and appear in call history.
            </small>
          </Panel>
          <Panel>
            <PanelHead
              title="Conversation"
              action={
                <Pill>
                  {call.state === "live" ? "Live transcript" : "Transcript"}
                </Pill>
              }
            />
            {call.lines.length === 0 ? (
              <Empty
                title="Your conversation appears here"
                description="Start a test call to see the dialogue as it happens."
              />
            ) : (
              <div aria-live="polite" data-testid="live-transcript">
                {call.lines.map((line, i) => (
                  <ChatMessage
                    key={i}
                    from={line.speaker === "agent" ? "agent" : "caller"}
                    initial={
                      line.speaker === "agent"
                        ? agent
                          ? initials(agent.name)
                          : "A"
                        : "Y"
                    }
                    name={line.speaker === "agent" ? agent?.name : "You"}
                  >
                    {line.text}
                  </ChatMessage>
                ))}
              </div>
            )}
            {call.toolRuns.length > 0 && (
              <>
                <H3>Tool activity</H3>
                <div data-testid="tool-activity">
                  {call.toolRuns.map((run, i) => (
                    <FooterRow key={i}>
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
                    </FooterRow>
                  ))}
                </div>
              </>
            )}
            {fields.length > 0 &&
              (call.state !== "idle" ||
                Object.keys(call.values).length > 0) && (
                <>
                  <H3>Captured details</H3>
                  <DetailList
                    data-testid="captured-fields"
                    items={fields.map((f) => [
                      `${f.label}${f.required ? " *" : ""}`,
                      call.values[f.key] === undefined ? (
                        <span className="text-muted">not yet</span>
                      ) : (
                        String(call.values[f.key])
                      ),
                    ])}
                  />
                </>
              )}
          </Panel>
        </WideSplit>
      )}
    </>
  );
}
