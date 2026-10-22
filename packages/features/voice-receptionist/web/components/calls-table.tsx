"use client";
import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
import { ChatMessage, DataTable, Td, Th, Tr } from "@clinic/ui";
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
    <DataTable>
      <thead>
        <tr>
          <Th scope="col">Call</Th>
          <Th scope="col">Agent</Th>
          <Th scope="col">Time</Th>
          <Th scope="col">Duration</Th>
          <Th scope="col">Status</Th>
          <Th scope="col">Details captured</Th>
          <Th scope="col">How it ended</Th>
        </tr>
      </thead>
      <tbody>
        {calls.length ? (
          calls.map((call) => (
            <Tr key={call.id}>
              <Td>
                <Link
                  className="focus-ring flex items-center gap-2.5"
                  href={`/voice-receptionist/calls/${call.id}`}
                >
                  <span className="grid size-[31px] place-items-center rounded-full bg-brand-soft text-brand-ink">
                    <ArrowUpRight size={16} />
                  </span>
                  <div>
                    <strong>{channelLabel(call.channel)}</strong>
                    <small className="block text-[12px] text-muted">
                      {call.id.slice(0, 8)}
                    </small>
                  </div>
                </Link>
              </Td>
              <Td>{call.agent_name || "Deleted agent"}</Td>
              <Td>{dateLabel(call.started_at, timezone)}</Td>
              <Td>{callDuration(call.duration_seconds)}</Td>
              <Td>
                <Badge>{statusLabel(call.status)}</Badge>
              </Td>
              <Td>{call.captured_count || "—"}</Td>
              <Td>{reasonLabel(call.end_reason)}</Td>
            </Tr>
          ))
        ) : (
          <Tr>
            <Td colSpan={7}>
              <Empty title={empty.title} description={empty.description} />
            </Td>
          </Tr>
        )}
      </tbody>
    </DataTable>
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
      {turns.map((turn, index) => {
        const agent = turn.speaker === "Agent";
        return (
          <ChatMessage
            key={index}
            from={agent ? "agent" : "caller"}
            initial={agent ? (agentName[0] ?? "A") : "C"}
            name={`${agent ? agentName : "Caller"} · ${turn.time}`}
          >
            {turn.text}
          </ChatMessage>
        );
      })}
    </div>
  );
}
