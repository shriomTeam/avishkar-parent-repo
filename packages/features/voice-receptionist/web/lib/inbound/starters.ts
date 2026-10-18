import type { Tool } from "./api";
import { newField, toDraft, type Draft } from "./draft";

export const STARTERS = {
  "Front desk receptionist": {
    prompt: (clinic: string) =>
      `You are the front desk receptionist for ${clinic}. You answer calls, answer simple questions about the clinic's services, and collect the caller's details so the team can call them back. Be warm, polite and brief. If you do not know something, say the team will follow up.`,
    greeting: (clinic: string) =>
      `Thanks for calling ${clinic}, how can I help you today?`,
  },
  "Enquiry assistant": {
    prompt: (clinic: string) =>
      `You help people who call ${clinic} with questions about treatments and pricing. Answer simply, never give medical advice, and offer to have the team follow up. Collect the caller's contact details.`,
    greeting: (clinic: string) =>
      `Hello, you've reached ${clinic}. What would you like to know?`,
  },
  "After-hours assistant": {
    prompt: (clinic: string) =>
      `${clinic} is closed right now. Let callers know, answer basic questions, and take a message so the team can call back when the clinic opens. Be calm and brief.`,
    greeting: (clinic: string) =>
      `Thanks for calling ${clinic}. We're closed at the moment, but I can take a message.`,
  },
} as const;

export type StarterName = keyof typeof STARTERS;

/** A new agent pre-filled with a sensible prompt and the usual details to capture. */
export function starterDraft(
  name: string,
  starter: StarterName,
  clinic: string,
  tools: Tool[] = [],
): Draft {
  const fields = [
    {
      label: "Caller name",
      key: "caller_name",
      data_type: "text" as const,
      required: true,
    },
    {
      label: "Phone number",
      key: "phone_number",
      data_type: "phone" as const,
      required: true,
    },
    {
      label: "Reason for calling",
      key: "reason_for_calling",
      data_type: "text" as const,
      required: false,
    },
  ].map((f) => ({ ...newField(), ...f, keyTouched: true }));
  return {
    ...toDraft(),
    name,
    description: starter,
    prompt: STARTERS[starter].prompt(clinic),
    greeting: STARTERS[starter].greeting(clinic),
    fields,
    tool_ids: tools
      .filter((t) => t.builtin_key === "create_lead" && t.enabled)
      .map((t) => t.id),
  };
}
