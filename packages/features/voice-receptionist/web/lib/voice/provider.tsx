"use client";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useAuth } from "@clinic/core/web/auth/provider";
import {
  ApiError,
  createInboundApi,
  type Agent,
  type CallSummary,
  type InboundApi,
  type Tool,
  type Variable,
  type BuiltinVariable,
} from "../inbound/api";

const CALLS_LOADED = 200; // the API's maximum page; plenty for history, overview and per-agent counts

type Value = {
  api: InboundApi;
  agents: Agent[] | null;
  calls: CallSummary[] | null;
  tools: Tool[] | null;
  variables: Variable[] | null;
  builtinVariables: BuiltinVariable[];
  error: string;
  retry: () => void;
  reloadCalls: () => Promise<void>;
  upsertAgent: (agent: Agent) => void;
  removeAgent: (id: string) => void;
  upsertTool: (tool: Tool) => void;
  removeTool: (id: string) => void;
  upsertVariable: (variable: Variable) => void;
  removeVariable: (id: string) => void;
  /** Which agents use a variable changes when an agent is saved, so the list is read again. */
  reloadVariables: () => Promise<void>;
};

const Context = createContext<Value | null>(null);

/** Real agents, calls, tools and variables for the signed-in workspace. */
export function VoiceDataProvider({ children }: { children: ReactNode }) {
  const { auth } = useAuth();
  const api = useMemo(
    () =>
      createInboundApi({
        csrf: auth.csrf_token,
        tenantId: auth.workspace?.id,
      }),
    [auth.csrf_token, auth.workspace?.id],
  );
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [calls, setCalls] = useState<CallSummary[] | null>(null);
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [variables, setVariables] = useState<Variable[] | null>(null);
  const [builtinVariables, setBuiltinVariables] = useState<BuiltinVariable[]>(
    [],
  );
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const [a, c, t, v] = await Promise.all([
        api.listAgents(),
        api.listCalls(undefined, CALLS_LOADED),
        api.listTools(),
        api.listVariables(),
      ]);
      setAgents(a);
      setCalls(c);
      setTools(t);
      setVariables(v.custom);
      setBuiltinVariables(v.builtin);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not load your voice data.",
      );
    }
  }, [api]);
  useEffect(() => {
    void load();
  }, [load]);

  const value: Value = {
    api,
    agents,
    calls,
    tools,
    variables,
    builtinVariables,
    error,
    retry: () => void load(),
    reloadCalls: async () => {
      try {
        setCalls(await api.listCalls(undefined, CALLS_LOADED));
      } catch {
        // keep the list we have; the next navigation reloads it
      }
    },
    upsertAgent: (agent) =>
      setAgents((list) =>
        list?.some((a) => a.id === agent.id)
          ? list.map((a) => (a.id === agent.id ? agent : a))
          : [agent, ...(list ?? [])],
      ),
    removeAgent: (id) =>
      setAgents((list) => list?.filter((a) => a.id !== id) ?? null),
    upsertTool: (tool) =>
      setTools((list) =>
        list?.some((t) => t.id === tool.id)
          ? list.map((t) => (t.id === tool.id ? tool : t))
          : [...(list ?? []), tool],
      ),
    upsertVariable: (variable) =>
      setVariables((list) =>
        list?.some((v) => v.id === variable.id)
          ? list.map((v) => (v.id === variable.id ? variable : v))
          : [...(list ?? []), variable].sort((a, b) =>
              a.name.localeCompare(b.name),
            ),
      ),
    removeVariable: (id) =>
      setVariables((list) => list?.filter((v) => v.id !== id) ?? null),
    reloadVariables: async () => {
      try {
        setVariables((await api.listVariables()).custom);
      } catch {
        // keep the list we have
      }
    },
    removeTool: (id) => {
      setTools((list) => list?.filter((t) => t.id !== id) ?? null);
      // The server drops the tool from every agent that used it; mirror that here.
      setAgents(
        (list) =>
          list?.map((a) => ({
            ...a,
            tool_ids: (a.tool_ids ?? []).filter((t) => t !== id),
          })) ?? null,
      );
    },
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

type Loaded = Value & {
  agents: Agent[];
  calls: CallSummary[];
  tools: Tool[];
  variables: Variable[];
};

/** Use inside <VoiceBoundary>, which renders its children only once agents and calls have loaded. */
export function useVoice(): Loaded {
  const value = useContext(Context);
  if (!value) throw new Error("VoiceDataProvider is required");
  if (!value.agents || !value.calls || !value.tools || !value.variables)
    throw new Error("useVoice must be used inside <VoiceBoundary>");
  return value as Loaded;
}

export function useVoiceStatus() {
  const value = useContext(Context);
  if (!value) throw new Error("VoiceDataProvider is required");
  return value;
}
