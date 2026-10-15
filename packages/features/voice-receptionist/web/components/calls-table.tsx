"use client";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { Badge, Empty } from "./ui";
import type { Call, TranscriptTurn } from "../lib/types";
import { dateLabel, duration } from "../lib/format";
export function CallsTable({
  calls,
  timezone,
}: {
  calls: Call[];
  timezone: string;
}) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Caller</th>
            <th scope="col">Agent</th>
            <th scope="col">Time</th>
            <th scope="col">Duration</th>
            <th scope="col">Status</th>
            <th scope="col">Outcome</th>
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
                      <strong>{call.caller}</strong>
                      <small>{call.phone}</small>
                    </div>
                  </Link>
                </td>
                <td>{call.agentName}</td>
                <td>{dateLabel(call.startedAt, timezone)}</td>
                <td>{duration(call.durationSeconds)}</td>
                <td>
                  <Badge>{call.status}</Badge>
                </td>
                <td>{call.outcome}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={6}>
                <Empty
                  title="No calls match your filters"
                  description="Try another caller, agent or status."
                />
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
