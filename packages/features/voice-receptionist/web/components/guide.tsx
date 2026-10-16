"use client";
import Link from "next/link";
import { Heading } from "./ui";
export const guide: [string, string, string][] = [
  [
    "/voice-receptionist",
    "Overview",
    "Call volume, completion, captured leads, latency and recent calls.",
  ],
  [
    "/voice-receptionist/agents",
    "Voice agents",
    "Published and draft assistants. Start the create-agent flow.",
  ],
  [
    "/voice-receptionist/agents/agent-sophie",
    "Agent editor",
    "Prompt, greeting, voice, model, variables, tools and versions.",
  ],
  [
    "/voice-receptionist/test",
    "Test studio",
    "Simulated browser conversation with dialogue and tool results.",
  ],
  [
    "/voice-receptionist/numbers",
    "Phone numbers",
    "Add sample carrier numbers and assign inbound agents.",
  ],
  [
    "/voice-receptionist/calls",
    "Call history",
    "Search and filter conversations; export sample records.",
  ],
  [
    "/voice-receptionist/calls/CA_1048",
    "Call details",
    "Transcript, summary, execution results and latency.",
  ],
  [
    "/voice-receptionist/tools",
    "Tools",
    "Configure API tools and inspect simulated execution.",
  ],
  [
    "/voice-receptionist/variables",
    "Variables",
    "Static and runtime context with a resolved prompt preview.",
  ],
  [
    "/voice-receptionist/settings",
    "Settings",
    "Workspace, team, privacy preferences and audit log.",
  ],
  [
    "/login",
    "Google sign-in",
    "Sign in securely with Google to access your workspace.",
  ],
  ["/onboarding", "Onboarding", "Practice details and first workspace setup."],
];
export function Guide() {
  return (
    <>
      <Heading
        title="Page-by-page design"
        description="The complete V1 frontend journey, ready to explore."
        actions={
          <Link className="button primary" href="/voice-receptionist">
            Open dashboard
          </Link>
        }
      />
      <div className="note guide-note">
        Avishkar lime #A1FF62 · charcoal #201D1D · grey #F4F4F4 · soft green
        #EDFFE1. Changes last until refresh. Sample records and actions are for
        design review.
      </div>
      <div className="guidegrid">
        {guide.map(([path, title, description], index) => (
          <Link className="card" key={path} href={path}>
            <span className="number">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <h2>{title}</h2>
              <p>{description}</p>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
