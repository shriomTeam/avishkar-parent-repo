import type {
  Agent,
  AgentConfig,
  Call,
  DemoState,
  TranscriptTurn,
} from "@/lib/voice/types";
const frontDesk: AgentConfig = {
  name: "Sophie · Front desk",
  description: "Welcomes callers and captures new enquiries.",
  voice: "Sophie",
  language: "English (US)",
  model: "GPT-4.1 mini",
  interruptions: true,
  toolIds: ["tool-lead"],
  prompt:
    "You are {{agent_name}}, the friendly AI receptionist for {{company_name}}. Greet callers, answer using the supplied practice information, and collect their name, phone number and service of interest. Confirm details before calling create_lead. Never invent information. Offer a staff callback when you cannot help.",
  greeting:
    "Hi! Thank you for calling {{company_name}}. I’m Sophie, your virtual receptionist. How can I help you today?",
};
const config = (changes: Partial<AgentConfig>) => ({
  ...frontDesk,
  ...changes,
});
export function makeTranscript(
  caller: string,
  workspace: string,
  greeting?: string,
): TranscriptTurn[] {
  return [
    {
      speaker: "Agent",
      time: "00:00",
      text:
        greeting ||
        `Hi! Thank you for calling ${workspace}. How can I help you today?`,
    },
    {
      speaker: "Caller",
      time: "00:08",
      text: "I’d like someone to call me back about a consultation.",
    },
    {
      speaker: "Agent",
      time: "00:15",
      text: "Of course. May I have your name and the best number for the team to reach you?",
    },
    {
      speaker: "Caller",
      time: "00:24",
      text: `${caller}. You can use the number I’m calling from.`,
    },
    {
      speaker: "Agent",
      time: "00:32",
      text: `Thanks, ${caller.split(" ")[0]}. I’ll share your details with our front desk. Is that correct?`,
    },
    { speaker: "Caller", time: "00:41", text: "Yes, that’s right." },
    {
      speaker: "Agent",
      time: "00:45",
      text: "Your enquiry has been saved. Our team will call you back. Thank you!",
    },
  ];
}
export function createSeed(): DemoState {
  const agents: [Agent, Agent, Agent] = [
    {
      id: "agent-sophie",
      draft: config({}),
      versions: [
        {
          id: "version-sophie-1",
          number: 1,
          publishedAt: "2026-10-07T16:15:00Z",
          config: config({}),
        },
      ],
    },
    {
      id: "agent-alex",
      draft: config({
        name: "Alex · Enquiries",
        voice: "Alex",
        description: "Collects service enquiries for a staff callback.",
        greeting: "Hello! How can I help you today?",
        prompt: "Collect new service enquiries and offer a staff callback.",
      }),
      versions: [],
    },
    {
      id: "agent-afterhours",
      draft: config({
        name: "After-hours assistant",
        description: "Keeps your practice available after closing.",
        prompt: "Collect caller details after hours.",
        greeting: "Thanks for calling. Our team is currently away.",
      }),
      versions: [],
    },
  ];
  agents[1].versions = [
    {
      id: "version-alex-1",
      number: 1,
      publishedAt: "2026-10-07T17:00:00Z",
      config: { ...agents[1].draft },
    },
  ];
  const base: Call = {
    id: "CA_1048",
    caller: "Morgan Lee",
    phone: "+1 (415) 555-0101",
    agentId: "agent-sophie",
    agentName: frontDesk.name,
    version: 1,
    startedAt: "2026-10-09T17:42:00Z",
    durationSeconds: 204,
    status: "Completed",
    outcome: "Lead created",
    latencyMs: 520,
    cost: 0.17,
    transcript: [],
    toolExecutions: [],
    recording: true,
    summary:
      "Caller requested a consultation callback. Name and callback number were confirmed and a lead was saved for the front desk.",
  };
  const calls: Call[] = [
    base,
    {
      ...base,
      id: "CA_1047",
      caller: "Taylor Reed",
      phone: "+1 (415) 555-0102",
      startedAt: "2026-10-09T17:28:00Z",
      durationSeconds: 136,
      outcome: "Question answered",
      latencyMs: 480,
      cost: 0.11,
      summary:
        "Caller asked about practice opening hours and received the sample information.",
    },
    {
      ...base,
      id: "CA_1046",
      caller: "Jordan Ellis",
      phone: "+1 (415) 555-0103",
      agentId: "agent-alex",
      agentName: agents[1].draft.name,
      startedAt: "2026-10-08T17:13:00Z",
      durationSeconds: 248,
      latencyMs: 610,
      cost: 0.21,
    },
    {
      ...base,
      id: "CA_1045",
      caller: "Unknown caller",
      phone: "+1 (415) 555-0104",
      startedAt: "2026-10-08T16:56:00Z",
      durationSeconds: 42,
      status: "Failed",
      outcome: "Connection lost",
      latencyMs: null,
      cost: 0.03,
      recording: false,
      summary:
        "Connection lost before a conversation began. No caller information was captured.",
    },
    {
      ...base,
      id: "CA_1044",
      caller: "Casey Smith",
      phone: "Browser test",
      startedAt: "2026-10-07T16:31:00Z",
      durationSeconds: 112,
      outcome: "Test completed",
      latencyMs: 490,
      cost: 0,
    },
  ];
  calls.forEach((call) => {
    if (call.status === "Failed") return;
    call.transcript =
      call.outcome === "Question answered"
        ? [
            {
              speaker: "Caller",
              time: "00:08",
              text: "What are your opening hours?",
            },
            {
              speaker: "Agent",
              time: "00:15",
              text: "Our sample practice is open Monday to Friday, 9 AM to 5 PM.",
            },
          ]
        : makeTranscript(call.caller, "Bloom Aesthetics");
    if (call.outcome === "Lead created")
      call.toolExecutions = [
        {
          toolName: "create_lead",
          durationMs: 312,
          success: true,
          input: {
            name: call.caller,
            phone: call.phone,
            service: "Consultation",
            consent: true,
          },
          output: { success: true, lead_id: `L-${call.id}` },
          idempotencyKey: `${call.id}_lead`,
        },
      ];
  });
  return {
    workspace: {
      name: "Bloom Aesthetics",
      timezone: "America/Los_Angeles",
      address: "100 Example Avenue, San Francisco",
      phone: "+14155550100",
      recordCalls: false,
      transcriptRetention: "30 days",
      recordingRetention: "7 days",
    },
    agents,
    calls,
    numbers: [
      {
        id: "number-main",
        number: "+14155550100",
        provider: "Telnyx · SIP",
        agentId: "agent-sophie",
      },
    ],
    tools: [
      {
        id: "tool-lead",
        name: "create_lead",
        description: "Capture an enquiry for the front desk.",
        endpoint: "/api/v1/leads",
        method: "POST",
        timeoutSeconds: 5,
        enabled: true,
        schema: JSON.stringify(
          {
            type: "object",
            properties: {
              name: { type: "string" },
              phone: { type: "string" },
              service: { type: "string" },
            },
            required: ["name", "phone", "service"],
          },
          null,
          2,
        ),
      },
    ],
    variables: [
      { id: "var-agent", name: "agent_name", value: "Sophie", type: "Static" },
      {
        id: "var-company",
        name: "company_name",
        value: "Bloom Aesthetics",
        type: "Static",
      },
      {
        id: "var-caller",
        name: "caller_number",
        value: "Resolved at call start",
        type: "Call",
      },
      {
        id: "var-date",
        name: "current_date",
        value: "Resolved at call start",
        type: "Runtime",
      },
      {
        id: "var-customer",
        name: "customer_name",
        value: "Collected during conversation",
        type: "Runtime",
      },
    ],
    audit: [
      {
        id: "audit-initial",
        event: "Agent version published",
        actor: "Jamie Davis",
        at: "2026-10-07T16:15:00Z",
      },
    ],
  };
}
