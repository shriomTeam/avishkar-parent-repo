export type AgentConfig = {
  name: string;
  description: string;
  prompt: string;
  greeting: string;
  voice: string;
  language: string;
  model: string;
  interruptions: boolean;
  toolIds: string[];
};
export type AgentVersion = {
  id: string;
  number: number;
  publishedAt: string;
  config: AgentConfig;
};
export type Agent = {
  id: string;
  draft: AgentConfig;
  versions: AgentVersion[];
};
export type TranscriptTurn = {
  speaker: "Agent" | "Caller";
  time: string;
  text: string;
};
export type ToolExecution = {
  toolName: string;
  durationMs: number;
  success: boolean;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  idempotencyKey: string;
};
export type Call = {
  id: string;
  caller: string;
  phone: string;
  agentId: string;
  agentName: string;
  version: number;
  startedAt: string;
  durationSeconds: number;
  status: "Completed" | "Failed";
  outcome: string;
  latencyMs: number | null;
  cost: number;
  transcript: TranscriptTurn[];
  toolExecutions: ToolExecution[];
  recording: boolean;
  summary: string;
};
export type Tool = {
  id: string;
  name: string;
  description: string;
  endpoint: string;
  method: "POST" | "GET";
  schema: string;
  enabled: boolean;
  timeoutSeconds: number;
};
export type Workspace = {
  name: string;
  timezone: string;
  address: string;
  phone: string;
  recordCalls: boolean;
  transcriptRetention: string;
  recordingRetention: string;
};
export type AuditEvent = {
  id: string;
  event: string;
  actor: string;
  at: string;
};
export type DemoState = {
  workspace: Workspace;
  agents: Agent[];
  calls: Call[];
  tools: Tool[];
  audit: AuditEvent[];
};
export type DemoCommand =
  | { type: "save-agent"; agent: Agent; event: string }
  | { type: "save-tool"; tool: Tool }
  | { type: "save-workspace"; workspace: Workspace }
  | { type: "add-call"; call: Call }
  | { type: "reset" };
