import type { Schemas } from "@clinic/api-client";

export type Agent = Schemas["AgentOut"];
export type AgentInput = Schemas["AgentIn"];
export type FieldInput = Schemas["FieldIn"];
export type CallSummary = Schemas["CallSummaryOut"];
export type CallDetail = Schemas["CallDetailOut"];
export type TestCall = Schemas["TestCallOut"];
export type Tool = Schemas["ToolOut"];
export type ToolInput = Schemas["ToolIn"];
export type ToolTestResult = Schemas["ToolTestOut"];
export type ToolExecution = Schemas["ToolExecutionOut"];
export type CatalogItem = Schemas["CatalogItemOut"];

// Same-origin: Next rewrites /api/platform/* to the FastAPI backend, so the session cookie is sent.
const BASE = "/api/platform/features/voice_receptionist/inbound";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

function messageFor(status: number): string {
  if (status === 401) return "Your session ended. Please sign in again.";
  if (status === 403)
    return "Your role cannot do this, or your session needs a refresh.";
  if (status === 404) return "That item no longer exists.";
  if (status === 409) return "That name is already in use.";
  if (status === 422)
    return "Some values are not valid. Check the highlighted settings.";
  if (status === 429)
    return "Too many calls are in progress. End one and try again.";
  return "Something went wrong. Please retry.";
}

/** The API explains rejected tool and agent settings in plain words; show those instead of a generic line. */
async function detailOf(response: Response): Promise<string | null> {
  if (![409, 422].includes(response.status)) return null;
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === "string" && /\s/.test(body.detail)
      ? body.detail
      : null;
  } catch {
    return null;
  }
}

export function createInboundApi(session: { csrf: string; tenantId?: string }) {
  async function send(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<Response> {
    const headers: Record<string, string> = { "X-CSRF-Token": session.csrf };
    if (session.tenantId) headers["X-Tenant-Id"] = session.tenantId;
    if (body !== undefined) headers["Content-Type"] = "application/json";
    let response: Response;
    try {
      response = await fetch(`${BASE}${path}`, {
        method,
        credentials: "same-origin",
        cache: "no-store",
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiError(
        0,
        "Could not reach the server. Check your connection.",
      );
    }
    if (!response.ok)
      throw new ApiError(
        response.status,
        (await detailOf(response)) ?? messageFor(response.status),
      );
    return response;
  }
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
  ): Promise<T> {
    const response = await send(method, path, body);
    return response.status === 204
      ? (undefined as T)
      : ((await response.json()) as T);
  }
  return {
    listAgents: () => request<Agent[]>("GET", "/agents"),
    createAgent: (body: AgentInput) => request<Agent>("POST", "/agents", body),
    updateAgent: (id: string, body: AgentInput) =>
      request<Agent>("PUT", `/agents/${id}`, body),
    deleteAgent: (id: string) => request<void>("DELETE", `/agents/${id}`),
    listCalls: (agentId?: string, limit = 25) =>
      request<CallSummary[]>(
        "GET",
        `/calls?limit=${limit}${agentId ? `&agent_id=${agentId}` : ""}`,
      ),
    getCall: (id: string, includeEvents = false) =>
      request<CallDetail>(
        "GET",
        `/calls/${id}?include_events=${includeEvents}`,
      ),
    /** The call's audio. Fetched with the session headers, so it cannot be a plain <audio src>. */
    getRecording: async (id: string) =>
      (await send("GET", `/calls/${id}/recording`)).blob(),
    listTools: () => request<Tool[]>("GET", "/tools"),
    toolCatalog: () => request<CatalogItem[]>("GET", "/tools/catalog"),
    addInternalTool: (key: string) =>
      request<Tool>("POST", "/tools/internal", { builtin_key: key }),
    createTool: (body: ToolInput) => request<Tool>("POST", "/tools", body),
    updateTool: (id: string, body: ToolInput) =>
      request<Tool>("PUT", `/tools/${id}`, body),
    deleteTool: (id: string) => request<void>("DELETE", `/tools/${id}`),
    testTool: (id: string, input: Record<string, unknown>) =>
      request<ToolTestResult>("POST", `/tools/${id}/test`, { input }),
    listExecutions: (limit = 25) =>
      request<ToolExecution[]>("GET", `/tool-executions?limit=${limit}`),
    startTestCall: (agentId: string) =>
      request<TestCall>("POST", `/agents/${agentId}/test-call`),
  };
}

export type InboundApi = ReturnType<typeof createInboundApi>;
