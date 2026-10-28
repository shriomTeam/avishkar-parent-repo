"use client";
import { initials } from "@clinic/core/web/auth/types";
import { useAuth } from "@clinic/core/web/auth/provider";
import Link from "next/link";
import { useState } from "react";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import { callDuration, plural } from "../lib/format";
import {
  Avatar,
  buttonStyles,
  FooterRow,
  Panel,
  panelLinkStyles,
  PanelHead,
  Pill,
  StatGrid,
  WideSplit,
} from "@clinic/ui";
import { Heading, Metric, Badge, Dropdown, Empty } from "./ui";
import { CallsTable } from "./calls-table";
import { VoiceBoundary } from "./voice-boundary";
import { OverviewSkeleton } from "./skeletons";

const DAY = 86_400_000;

export function Overview() {
  return (
    <VoiceBoundary fallback={<OverviewSkeleton />}>
      <Summary />
    </VoiceBoundary>
  );
}

function Summary() {
  const { auth } = useAuth();
  const manager = ["owner", "office_manager"].includes(
    auth.memberships.find((m) => m.workspace_id === auth.workspace?.id)?.role ??
      "",
  );
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
            <Dropdown
              inline
              className="min-w-[130px] max-app:flex-1"
              label="Overview period"
              hideLabel
              value={String(period)}
              onChange={(value) => setPeriod(Number(value))}
              options={[
                { value: "7", label: "Last 7 days" },
                { value: "30", label: "Last 30 days" },
              ]}
            />
            {manager && (
              <Link
                className={buttonStyles("brand")}
                href="/voice-receptionist/agents"
              >
                Manage agents
              </Link>
            )}
          </>
        }
      />
      <StatGrid>
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
      </StatGrid>
      <WideSplit>
        <Panel>
          <PanelHead
            title="Call activity"
            action={<Pill>{plural(calls.length, "call")} in this period</Pill>}
          />
          <div
            className={`relative flex h-[195px] items-end bg-[repeating-linear-gradient(to_top,transparent_0,transparent_44px,#f0eff4_45px,#f0eff4_46px)] px-3 pb-6 min-[1500px]:h-[240px] ${period === 30 ? "gap-[5px] max-app:gap-[3px]" : "gap-[17px] max-app:gap-2.5"}`}
            role="img"
            aria-label={buckets
              .map((b) => `${b.key}: ${b.count} calls`)
              .join("; ")}
          >
            {buckets.map((b, index) => (
              <div
                className={`relative flex-1 rounded-t-[5px] bg-[#d1f5bc] transition-[height] duration-200 last:bg-brand hover:bg-[#7fda44] ${period === 30 ? "min-w-[3px]" : ""}`}
                key={b.key}
                style={{ height: `${Math.max(2, (b.count / max) * 90)}%` }}
                title={`${b.key}: ${b.count} calls`}
              >
                {(period === 7 || index % 5 === 0) && (
                  <span
                    className={`absolute -bottom-[25px] left-1/2 -translate-x-1/2 text-muted ${period === 30 ? "text-[10px]" : "text-[12px]"}`}
                  >
                    {period === 7 ? b.day : Number(b.key.slice(-2))}
                  </span>
                )}
              </div>
            ))}
          </div>
          <div className="mt-3 text-[12px] text-muted">
            Browser test calls · dates in UTC
          </div>
        </Panel>
        <Panel>
          <PanelHead
            title="Your agents"
            action={
              <Link
                className={panelLinkStyles}
                href="/voice-receptionist/agents"
              >
                View all
              </Link>
            }
          />
          {agents.length === 0 && (
            <Empty
              title="No agents yet"
              description="Create one to start taking calls."
            />
          )}
          {agents.slice(0, 2).map((agent) => (
            <Link
              className="focus-ring my-[18px] flex items-center gap-3"
              key={agent.id}
              href={`/voice-receptionist/agents/${agent.id}`}
            >
              <Avatar>{initials(agent.name)}</Avatar>
              <div className="flex-1">
                <strong className="text-[14px]">{agent.name}</strong>
                <small className="block text-[12px] text-muted">
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
          <FooterRow>
            <span>Active agents</span>
            <strong>{agents.filter((a) => a.is_active).length}</strong>
          </FooterRow>
        </Panel>
      </WideSplit>
      <Panel>
        <PanelHead
          title="Recent calls"
          action={
            <Link className={panelLinkStyles} href="/voice-receptionist/calls">
              View call history
            </Link>
          }
        />
        <CallsTable
          calls={all.slice(0, 4)}
          timezone={state?.workspace.timezone || "UTC"}
          empty={{
            title: "No calls yet",
            description: "Take a test call in Test studio to see it here.",
          }}
        />
      </Panel>
    </>
  );
}
