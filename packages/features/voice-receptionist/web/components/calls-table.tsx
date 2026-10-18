"use client";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Badge, Empty } from "./ui";
import type { CallSummary } from "../lib/inbound/api";
import type { TranscriptTurn } from "../lib/types";
import {
  callDuration,
  channelLabel,
  dateLabel,
  reasonLabel,
  statusLabel,
} from "../lib/format";

export function CallsTable({
  calls,
  timezone,
  empty = {
    title: "No calls match your filters",
    description: "Try another agent, status or call ID.",
  },
}: {
  calls: CallSummary[];
  timezone: string;
  empty?: { title: string; description: string };
}) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Call</th>
            <th scope="col">Agent</th>
            <th scope="col">Time</th>
            <th scope="col">Duration</th>
            <th scope="col">Status</th>
            <th scope="col">Details captured</th>
            <th scope="col">How it ended</th>
          </tr>
        </thead>
        <tbody>
          {calls.length ? (
            calls.map((call) => (
              <tr key={call.id}>
                <td>
                  <Link
                    className="callname"
                    href={`/voice-receptionist/calls/${call.id}`}
                  >
                    <span className="circle">
                      <ArrowUpRight size={16} />
                    </span>
                    <div>
                      <strong>{channelLabel(call.channel)}</strong>
                      <small>{call.id.slice(0, 8)}</small>
                    </div>
                  </Link>
                </td>
                <td>{call.agent_name || "Deleted agent"}</td>
                <td>{dateLabel(call.started_at, timezone)}</td>
                <td>{callDuration(call.duration_seconds)}</td>
                <td>
                  <Badge>{statusLabel(call.status)}</Badge>
                </td>
                <td>{call.captured_count || "—"}</td>
                <td>{reasonLabel(call.end_reason)}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={7}>
                <Empty title={empty.title} description={empty.description} />
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
export function Transcript({
  turns,
  agentName,
}: {
  turns: TranscriptTurn[];
  agentName: string;
}) {
  return (
    <div>
      {turns.map((turn, index) => (
        <div
          key={index}
          className={`chat ${turn.speaker === "Agent" ? "agent" : ""}`}
        >
          <div className={`avatar ${turn.speaker === "Caller" ? "dark" : ""}`}>
            {turn.speaker === "Agent" ? agentName[0] : "C"}
          </div>
          <div className="bubble">
            <strong>
              {turn.speaker === "Agent" ? agentName : "Caller"} · {turn.time}
            </strong>
            {turn.text}
          </div>
        </div>
      ))}
    </div>
  );
}
