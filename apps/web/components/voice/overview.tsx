"use client";
import Link from "next/link";
import { useState } from "react";
import { useDemo } from "@/lib/voice/demo/provider";
import { Heading, Metric, Badge } from "./ui";
import { CallsTable } from "./calls-table";
import { median } from "@/lib/voice/format";
export function Overview() {
  const { state } = useDemo();
  const [period, setPeriod] = useState(7);
  if (!state) return null;
  // Demo time is anchored to the most recent fixture/session call, not wall-clock expiry.
  const latest = Math.max(
    ...state.calls.map((c) => new Date(c.startedAt).getTime()),
  );
  const end = new Date(latest);
  end.setUTCHours(23, 59, 59, 999);
  const start = end.getTime() - period * 86400000;
  const calls = state.calls.filter(
    (c) => new Date(c.startedAt).getTime() > start,
  );
  const completed = calls.filter((c) => c.status === "Completed").length;
  const latencies = calls
    .flatMap((c) => (c.latencyMs === null ? [] : [c.latencyMs]))
    .sort((a, b) => a - b);
  const buckets = Array.from({ length: period }, (_, index) => {
    const date = new Date(end.getTime() - (period - 1 - index) * 86400000);
    const key = date.toISOString().slice(0, 10);
    return {
      key,
      day: new Intl.DateTimeFormat("en-US", {
        weekday: "short",
        timeZone: "UTC",
      }).format(date),
      count: calls.filter((c) => c.startedAt.slice(0, 10) === key).length,
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
          sub={`Sample calls · last ${period} days`}
          feature
        />
        <Metric
          label="Completed calls"
          value={`${calls.length ? ((completed / calls.length) * 100).toFixed(1) : "0"}%`}
          sub={`${completed} of ${calls.length} calls completed`}
        />
        <Metric
          label="Leads captured"
          value={String(
            calls.filter((c) => c.outcome === "Lead created").length,
          )}
          sub="Confirmed sample enquiries"
        />
        <Metric
          label="Response latency"
          value={`${median(latencies)} ms`}
          sub={`Median · P95 ${latencies[Math.max(0, Math.ceil(latencies.length * 0.95) - 1)] || 0} ms`}
        />
      </div>
      <div className="two">
        <section className="panel">
          <div className="panelHead">
            <h2>Call activity</h2>
            <span className="pill">{calls.length} calls in this period</span>
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
          <div className="legend">
            Inbound phone & browser calls · Sample metrics · dates in UTC
          </div>
        </section>
        <section className="panel">
          <div className="panelHead">
            <h2>Your agents</h2>
            <Link href="/voice-receptionist/agents">View all</Link>
          </div>
          {state.agents.slice(0, 2).map((agent) => {
            const agentCalls = state.calls.filter(
              (c) => c.agentId === agent.id,
            );
            return (
              <Link
                className="agentmini"
                key={agent.id}
                href={`/voice-receptionist/agents/${agent.id}`}
              >
                <div className="avatar">{agent.draft.name[0]}</div>
                <div className="grow">
                  <strong>{agent.draft.name}</strong>
                  <small>
                    {agentCalls.length} calls ·{" "}
                    {median(
                      agentCalls.flatMap((c) =>
                        c.latencyMs === null ? [] : [c.latencyMs],
                      ),
                    )}{" "}
                    ms median
                  </small>
                </div>
                <Badge>{agent.versions.length ? "Published" : "Draft"}</Badge>
              </Link>
            );
          })}
          <div className="rowline">
            <span>Connected numbers</span>
            <strong>{state.numbers.filter((n) => n.agentId).length}</strong>
          </div>
          <div className="rowline">
            <span>Sample call cost</span>
            <strong>
              ${calls.reduce((total, c) => total + c.cost, 0).toFixed(2)}
            </strong>
          </div>
        </section>
      </div>
      <section className="panel">
        <div className="panelHead">
          <h2>Recent calls</h2>
          <Link href="/voice-receptionist/calls">View call history</Link>
        </div>
        <CallsTable
          calls={calls.slice(0, 4)}
          timezone={state.workspace.timezone}
        />
      </section>
    </>
  );
}
