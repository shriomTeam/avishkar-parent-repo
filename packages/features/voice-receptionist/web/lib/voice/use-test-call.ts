"use client";
import { useEffect, useRef, useState } from "react";
import { ApiError, type Agent, type InboundApi } from "../inbound/api";
import { CallClient, type CallState } from "../inbound/call-client";

export type Line = { speaker: "caller" | "agent"; text: string };
export type ToolRun = {
  name: string;
  status: "running" | "ok" | "failed";
  durationMs?: number;
};

const REASONS: Record<string, string> = {
  caller_hangup: "You ended the call.",
  agent_ended: "The agent ended the call.",
  max_duration: "The call reached its time limit.",
  model_disconnected: "The voice service disconnected.",
  error: "The call ended because of an error.",
};

/** One browser test call: start it, follow it live, and learn when it has been saved. */
export function useTestCall(api: InboundApi, onFinished: () => void) {
  const [state, setState] = useState<CallState>("idle");
  const [lines, setLines] = useState<Line[]>([]);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [toolRuns, setToolRuns] = useState<ToolRun[]>([]);
  const [level, setLevel] = useState(0);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [callId, setCallId] = useState<string | null>(null);
  const client = useRef<CallClient | null>(null);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => () => client.current?.dispose(), []);
  useEffect(() => {
    if (state !== "live") return;
    const timer = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(timer);
  }, [state]);

  async function start(agent: Agent) {
    setError("");
    setReason("");
    setLines([]);
    setValues({});
    setToolRuns([]);
    setSeconds(0);
    setCallId(null);
    setState("connecting");
    let ticket;
    try {
      ticket = await api.startTestCall(agent.id);
    } catch (e) {
      setState("error");
      setError(e instanceof ApiError ? e.message : "Could not start the call.");
      return;
    }
    setCallId(ticket.call_id);
    const call = new CallClient({
      state: setState,
      level: setLevel,
      fields: setValues,
      interrupted: () => undefined,
      tool: (name, status, durationMs) =>
        setToolRuns((runs) => {
          if (status === "running") return [...runs, { name, status }];
          let open = -1;
          runs.forEach((r, index) => {
            if (r.name === name && r.status === "running") open = index;
          });
          return open < 0
            ? runs
            : runs.map((r, i) =>
                i === open ? { name, status, durationMs } : r,
              );
        }),
      // Each event carries the whole turn so far: replace the open turn, or start a new one.
      transcript: (speaker, text) =>
        setLines((prev) => {
          const last = prev.at(-1);
          return last && last.speaker === speaker
            ? [...prev.slice(0, -1), { speaker, text }]
            : [...prev, { speaker, text }];
        }),
      ended: (why) => {
        setReason(REASONS[why] ?? "The call ended.");
        finished.current();
      },
      error: (message) => {
        setError(message);
        finished.current();
      },
    });
    client.current = call;
    await call.start({
      path: ticket.ws_path,
      ticket: ticket.ticket,
      outputRate: ticket.output_rate,
    });
  }

  return {
    state,
    lines,
    values,
    toolRuns,
    level,
    seconds,
    error,
    reason,
    callId,
    busy: state === "connecting" || state === "live",
    start,
    hangup: () => client.current?.hangup(),
  };
}
