"use client";
import Link from "next/link";
import { buttonStyles, H2, Muted, Note } from "@clinic/ui";
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
    "Buy a phone number and choose which agent it belongs to.",
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
    "/settings",
    "Workspace settings",
    "Shared workspace details, member directory, privacy status and audit log.",
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
          <Link className={buttonStyles("brand")} href="/voice-receptionist">
            Open dashboard
          </Link>
        }
      />
      <Note className="mb-[22px]">
        Avishkar lime #A1FF62 · charcoal #201D1D · grey #F4F4F4 · soft green
        #EDFFE1. Changes last until refresh. Sample records and actions are for
        design review.
      </Note>
      <div className="grid grid-cols-2 gap-[18px] max-app:grid-cols-1">
        {guide.map(([path, title, description], index) => (
          <Link
            className="focus-ring flex gap-[18px] rounded-[13px] border border-line bg-white p-[23px] max-app:p-[18px]"
            key={path}
            href={path}
          >
            <span className="text-[25px] font-[650] text-brand-ink">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div>
              <H2>{title}</H2>
              <Muted>{description}</Muted>
            </div>
          </Link>
        ))}
      </div>
    </>
  );
}
