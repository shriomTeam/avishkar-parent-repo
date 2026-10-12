"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Mic } from "lucide-react";
import { useDemo } from "@/lib/voice/demo/provider";
import { makeTranscript } from "@/lib/voice/demo/seed";
import { resolvePrompt } from "@/lib/voice/format";
import type { AgentConfig, Call } from "@/lib/voice/types";
import { Heading, Select, Badge, Empty } from "./ui";
import { Transcript } from "./calls-table";
export function TestStudio() {
  const { state, run, busy } = useDemo();
  const params = useSearchParams();
  const [selected, setSelected] = useState(
    params.get("agent") || "agent-sophie",
  );
  const [session, setSession] = useState<{
    call: Call;
    config: AgentConfig;
  } | null>(null);
  const [active, setActive] = useState(false);
  const [saved, setSaved] = useState(false);
  if (!state) return null;
  const agent = state.agents.find((a) => a.id === selected);
  const config = agent?.draft;
  const start = () => {
    if (!agent || !config) return;
    const id = `TEST_${crypto.randomUUID().slice(0, 8)}`;
    const enabledTools = state.tools.filter(
      (t) => t.enabled && config.toolIds.includes(t.id),
    );
    const lead = enabledTools.find((t) => t.name === "create_lead");
    const greeting = resolvePrompt(config.greeting, state.variables, {
      current_date: new Date().toISOString().slice(0, 10),
      caller_number: "+14155550101",
      customer_name: "Morgan Lee",
    });
    const turns = makeTranscript("Morgan Lee", state.workspace.name, greeting);
    if (!lead)
      turns[turns.length - 1] = {
        speaker: "Agent",
        time: "00:45",
        text: "Thank you. Please contact our front desk to arrange your callback.",
      };
    const call: Call = {
      id,
      caller: "Morgan Lee",
      phone: "Browser test",
      agentId: agent.id,
      agentName: config.name,
      version: 0,
      startedAt: new Date().toISOString(),
      durationSeconds: 45,
      status: "Completed",
      outcome: lead ? "Lead created" : "Test completed",
      latencyMs: 490,
      cost: 0,
      transcript: turns,
      toolExecutions: lead
        ? [
            {
              toolName: lead.name,
              durationMs: 312,
              success: true,
              input: {
                name: "Morgan Lee",
                phone: "+14155550101",
                service: "Consultation",
                consent: true,
              },
              output: { success: true, lead_id: `L-${id}` },
              idempotencyKey: `${id}_lead`,
            },
          ]
        : [],
      recording: false,
      summary: lead
        ? "Simulated enquiry captured using the saved agent draft. A sample lead action succeeded."
        : "Simulated conversation completed using the saved agent draft. No lead action was enabled.",
    };
    setSession({ call, config: structuredClone(config) });
    setSaved(false);
    setActive(true);
  };
  const end = async () => {
    if (!session) return;
    if (
      await run(
        { type: "add-call", call: session.call },
        "Simulated call saved to call history",
      )
    ) {
      setActive(false);
      setSaved(true);
    }
  };
  return (
    <>
      <Heading
        title="Test studio"
        description="Try your agent before callers do. All conversations here are simulated."
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
      <div className="two">
        <section className="panel">
          <div className="panelHead">
            <h2>Browser call</h2>
            <Badge>Simulated</Badge>
          </div>
          <Select
            label="Agent"
            value={selected}
            disabled={active}
            onChange={(e) => {
              setSelected(e.target.value);
              setSession(null);
              setSaved(false);
            }}
          >
            <option value="" disabled>
              Select an agent
            </option>
            {state.agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.draft.name}
              </option>
            ))}
          </Select>
          {!agent && (
            <p role="alert">
              Selected agent is unavailable. Choose an agent to continue.
            </p>
          )}
          <div className="testcenter">
            <div className={`orb ${active ? "live" : ""}`}>
              <Mic size={32} />
            </div>
            <h2>
              {active
                ? `${config?.voice || "Agent"} is listening`
                : saved
                  ? "Test call completed"
                  : "Ready when you are"}
            </h2>
            <p>No microphone, carrier or AI provider is used.</p>
            <button
              className={`${active ? "danger" : "primary"} spaced`}
              disabled={!agent || busy}
              onClick={active ? end : start}
            >
              {active ? "End simulated call" : "Start simulated call"}
            </button>
          </div>
          {saved && session && (
            <div className="note">
              <strong>Test complete</strong>
              <p>Greeting delivered · sample conversation saved</p>
              <Link
                className="button spaced"
                href={`/voice-receptionist/calls/${session.call.id}`}
              >
                View saved call
              </Link>
            </div>
          )}
          <small>
            Uses the saved draft. Test calls are labeled v0 to distinguish
            unpublished draft tests from published versions.
          </small>
        </section>
        <section className="panel">
          <div className="panelHead">
            <h2>Conversation</h2>
            <span className="pill">Sample transcript</span>
          </div>
          {session ? (
            <>
              <Transcript
                turns={session.call.transcript}
                agentName={session.config.name}
              />
              {session.call.toolExecutions.length > 0 && (
                <div className="note">
                  00:44 · {session.call.toolExecutions[0]?.toolName} · Simulated
                  success · 312 ms
                </div>
              )}
            </>
          ) : (
            <Empty
              title="Your conversation appears here"
              description="Start a simulated call to review the dialogue and tool execution."
            />
          )}
        </section>
      </div>
    </>
  );
}
