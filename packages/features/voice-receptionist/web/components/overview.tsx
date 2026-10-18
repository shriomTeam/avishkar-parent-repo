"use client";
import Link from "next/link";
import { useState } from "react";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import { callDuration, plural } from "../lib/format";
import { Heading, Metric, Badge, Empty } from "./ui";
import { CallsTable } from "./calls-table";
import { VoiceBoundary } from "./voice-boundary";

const DAY = 86_400_000;

export function Overview() {
  return (
    <VoiceBoundary>
      <Summary />
    </VoiceBoundary>
  );
}

function Summary() {
  const { agents, calls: all } = useVoice();
  const { state } = useDemo();
  const [period, setPeriod] = useState(7);
  const end = new Date();
  end.setUTCHours(23, 59, 59, 999);
  const start = end.getTime() - period * DAY;
  const calls = all.filter((c) => new Date(c.started_at).getTime() > start);
  const completed = calls.filter((c) => c.status === "completed");
  const captured = calls.reduce((sum, c) => sum + (c.captured_count ?? 0), 0);
  const lengths = completed.flatMap((c) =>
    c.duration_seconds == null ? [] : [c.duration_seconds],
  );
  const average = lengths.length
    ? Math.round(lengths.reduce((a, b) => a + b, 0) / lengths.length)
    : null;
  const buckets = Array.from({ length: period }, (_, index) => {
    const date = new Date(end.getTime() - (period - 1 - index) * DAY);
    const key = date.toISOString().slice(0, 10);
    return {
      key,
      day: new Intl.DateTimeFormat("en-US", {
        weekday: "short",
        timeZone: "UTC",
      }).format(date),
      count: calls.filter((c) => c.started_at.slice(0, 10) === key).length,
    };
  });
  const max = Math.max(1, ...buckets.map((b) => b.count));
  return (
    <>
      <Heading
        title="Your practice, in conversation."
        description="A clear view of how your voice agents are doing."
        actions={
          <>
            <select
              className="period-select"
              aria-label="Overview period"
              value={period}
              onChange={(e) => setPeriod(Number(e.target.value))}
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
            </select>
            <Link className="button primary" href="/voice-receptionist/agents">
              Manage agents
            </Link>
          </>
        }
      />
      <div className="cards">
        <Metric
          label="Total calls"
          value={String(calls.length)}
          sub={`Last ${period} days`}
          feature
        />
        <Metric
          label="Completed calls"
          value={`${calls.length ? ((completed.length / calls.length) * 100).toFixed(1) : "0"}%`}
          sub={`${completed.length} of ${plural(calls.length, "call")} completed`}
        />
        <Metric
          label="Details captured"
          value={String(captured)}
          sub="Caller details saved from calls"
        />
        <Metric
          label="Average call length"
          value={average === null ? "—" : callDuration(average)}
          sub="Completed calls"
        />
      </div>
      <div className="two">
        <section className="panel">
          <div className="panelHead">
            <h2>Call activity</h2>
            <span className="pill">
              {plural(calls.length, "call")} in this period
            </span>
          </div>
          <div
            className={`chart ${period === 30 ? "chart-month" : ""}`}
            role="img"
            aria-label={buckets
              .map((b) => `${b.key}: ${b.count} calls`)
              .join("; ")}
          >
            {buckets.map((b, index) => (
              <div
                className="bar"
                key={b.key}
                style={{ height: `${Math.max(2, (b.count / max) * 90)}%` }}
                title={`${b.key}: ${b.count} calls`}
              >
                {(period === 7 || index % 5 === 0) && (
                  <span>{period === 7 ? b.day : Number(b.key.slice(-2))}</span>
                )}
              </div>
            ))}
          </div>
          <div className="legend">Browser test calls · dates in UTC</div>
        </section>
        <section className="panel">
          <div className="panelHead">
            <h2>Your agents</h2>
            <Link href="/voice-receptionist/agents">View all</Link>
          </div>
          {agents.length === 0 && (
            <Empty
              title="No agents yet"
              description="Create one to start taking calls."
            />
          )}
          {agents.slice(0, 2).map((agent) => (
            <Link
              className="agentmini"
              key={agent.id}
              href={`/voice-receptionist/agents/${agent.id}`}
            >
              <div className="avatar">{agent.name[0]}</div>
              <div className="grow">
                <strong>{agent.name}</strong>
                <small>
                  {plural(
                    all.filter((c) => c.agent_id === agent.id).length,
                    "call",
                  )}{" "}
                  · {plural(agent.fields?.length ?? 0, "detail")} to capture
                </small>
              </div>
              <Badge>{agent.is_active ? "Active" : "Disabled"}</Badge>
            </Link>
          ))}
          <div className="rowline">
            <span>Active agents</span>
            <strong>{agents.filter((a) => a.is_active).length}</strong>
          </div>
        </section>
      </div>
      <section className="panel">
        <div className="panelHead">
          <h2>Recent calls</h2>
          <Link href="/voice-receptionist/calls">View call history</Link>
        </div>
        <CallsTable
          calls={all.slice(0, 4)}
          timezone={state?.workspace.timezone || "UTC"}
          empty={{
            title: "No calls yet",
            description: "Take a test call in Test studio to see it here.",
          }}
        />
      </section>
    </>
  );
}
