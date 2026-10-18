"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useAuth } from "@clinic/core/web/auth/provider";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import { ApiError, type Agent } from "../lib/inbound/api";
import { toDraft, toInput, validate, type Draft } from "../lib/inbound/draft";
import {
  STARTERS,
  starterDraft,
  type StarterName,
} from "../lib/inbound/starters";
import { dateLabel } from "../lib/format";
import {
  Heading,
  Badge,
  Dialog,
  Field,
  Select,
  Tabs,
  FormError,
  Empty,
} from "./ui";
import {
  CaptureFields,
  ConfigurationFields,
  PrivacyFields,
  ToolFields,
} from "./agent-fields";
import { VoiceBoundary } from "./voice-boundary";

export function AgentList() {
  return (
    <VoiceBoundary>
      <List />
    </VoiceBoundary>
  );
}

function List() {
  const { agents, calls, tools, api, upsertAgent, upsertTool } = useVoice();
  const { notify } = useDemo();
  const { auth } = useAuth();
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function create(form: FormData) {
    const name = String(form.get("name")).trim();
    if (!name) return;
    setBusy(true);
    setError("");
    try {
      // New agents start able to create a lead, so make sure the clinic has that tool.
      let starterTools = tools;
      if (!tools.some((t) => t.builtin_key === "create_lead")) {
        const added = await api.addInternalTool("create_lead");
        upsertTool(added);
        starterTools = [...tools, added];
      }
      const draft = starterDraft(
        name,
        String(form.get("purpose")) as StarterName,
        auth.workspace?.name || "the clinic",
        starterTools,
      );
      const agent = await api.createAgent(toInput(draft));
      upsertAgent(agent);
      notify("Agent created");
      setCreating(false);
      router.push(`/voice-receptionist/agents/${agent.id}`);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not create the agent.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Heading
        title="Voice agents"
        description="Configure and test your practice’s voice assistants."
        actions={
          <button className="primary" onClick={() => setCreating(true)}>
            <Plus size={16} />
            Create agent
          </button>
        }
      />
      {agents.length === 0 ? (
        <section className="panel">
          <Empty
            title="No voice agents yet"
            description="Create your first agent, then try it from your browser in Test studio."
          />
        </section>
      ) : (
        <div className="agentgrid">
          {agents.map((agent) => {
            const agentCalls = calls.filter((c) => c.agent_id === agent.id);
            return (
              <article className="card agentcard" key={agent.id}>
                <div className="panelHead">
                  <div className="avatar">{agent.name[0]}</div>
                  <Badge>{agent.is_active ? "Active" : "Disabled"}</Badge>
                </div>
                <h2>{agent.name}</h2>
                <p>{agent.description || "No description yet."}</p>
                <div className="inline agent-pills">
                  <span className="pill">{agent.language}</span>
                  <span className="pill">{agent.voice}</span>
                </div>
                <div className="agentstats">
                  <div>
                    <strong>{agentCalls.length}</strong>
                    <small>Total calls</small>
                  </div>
                  <div>
                    <strong>{agent.fields?.length ?? 0}</strong>
                    <small>Details captured</small>
                  </div>
                </div>
                <Link
                  href={`/voice-receptionist/agents/${agent.id}`}
                  className="button"
                >
                  Open agent
                </Link>
              </article>
            );
          })}
        </div>
      )}
      {creating && (
        <Dialog title="Create a voice agent" onClose={() => setCreating(false)}>
          <p>
            Start with a name and a purpose. We fill in a prompt and the usual
            details to capture; you can change everything next.
          </p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              await create(new FormData(event.currentTarget));
            }}
          >
            <Field
              label="Agent name"
              name="name"
              required
              maxLength={80}
              pattern=".*\S.*"
            />
            <Select label="Purpose" name="purpose">
              {Object.keys(STARTERS).map((purpose) => (
                <option key={purpose}>{purpose}</option>
              ))}
            </Select>
            <FormError message={error} />
            <div className="actions dialog-actions">
              <button type="button" onClick={() => setCreating(false)}>
                Cancel
              </button>
              <button className="primary" disabled={busy}>
                Create agent
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}

export function AgentEditor({ id }: { id: string }) {
  return (
    <VoiceBoundary>
      <EditorLoader id={id} />
    </VoiceBoundary>
  );
}

function EditorLoader({ id }: { id: string }) {
  const { agents } = useVoice();
  const agent = agents.find((a) => a.id === id);
  if (!agent)
    return (
      <section className="panel">
        <Empty
          title="Agent not found"
          description="This agent may have been deleted."
        />
        <Link className="button" href="/voice-receptionist/agents">
          Back to agents
        </Link>
      </section>
    );
  return <Editor key={agent.id} agent={agent} />;
}

function Editor({ agent }: { agent: Agent }) {
  const { api, calls, tools, upsertAgent, removeAgent } = useVoice();
  const { state, notify } = useDemo();
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(() => toDraft(agent));
  const [tab, setTab] = useState("Configuration");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [deleting, setDeleting] = useState(false);

  const dirty = JSON.stringify(draft) !== JSON.stringify(toDraft(agent));
  const lastTest = calls.find((c) => c.agent_id === agent.id && c.is_test);
  const required = draft.fields.filter((f) => f.required).length;

  async function save() {
    const problem = validate(draft);
    if (problem) {
      setError(problem);
      setTab(
        problem.includes("field") || problem.includes("key")
          ? "What to capture"
          : "Configuration",
      );
      return;
    }
    setBusy(true);
    setError("");
    try {
      const saved = await api.updateAgent(agent.id, toInput(draft));
      upsertAgent(saved);
      setDraft(toDraft(saved));
      notify("Agent saved");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save the agent.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.deleteAgent(agent.id);
      removeAgent(agent.id);
      notify("Agent deleted. Its past calls are kept.");
      router.push("/voice-receptionist/agents");
    } catch (e) {
      setDeleting(false);
      setError(
        e instanceof ApiError ? e.message : "Could not delete the agent.",
      );
      setBusy(false);
    }
  }

  return (
    <>
      <Heading
        title={draft.name || agent.name}
        description={`Agent configuration · ${draft.is_active ? "Active" : "Disabled"}${dirty ? " · Unsaved changes" : ""}`}
        actions={
          <>
            <Link
              className="button"
              href={`/voice-receptionist/test?agent=${agent.id}`}
            >
              Test agent
            </Link>
            <button disabled={busy} onClick={() => setDeleting(true)}>
              Delete
            </button>
            <button
              className="primary"
              disabled={busy || !dirty}
              onClick={save}
            >
              Save changes
            </button>
          </>
        }
      />
      <Tabs
        tabs={["Configuration", "What to capture", "Tools", "Data & privacy"]}
        value={tab}
        onChange={setTab}
      />
      <FormError message={error} />
      <div className="editor">
        <section className="panel" role="tabpanel" aria-label={tab}>
          {tab === "Configuration" && (
            <ConfigurationFields draft={draft} onChange={setDraft} />
          )}
          {tab === "What to capture" && (
            <CaptureFields draft={draft} onChange={setDraft} />
          )}
          {tab === "Tools" && (
            <ToolFields draft={draft} onChange={setDraft} tools={tools} />
          )}
          {tab === "Data & privacy" && (
            <PrivacyFields draft={draft} onChange={setDraft} />
          )}
        </section>
        <div>
          <section className="panel">
            <div className="panelHead">
              <h2>Agent readiness</h2>
              <Badge>{agent.is_active ? "Active" : "Disabled"}</Badge>
            </div>
            <div className="summarylist">
              <div>
                <span>Prompt</span>
                <strong>
                  {draft.prompt.trim() ? "Configured" : "Missing"}
                </strong>
              </div>
              <div>
                <span>Voice</span>
                <strong>
                  {draft.voice} · {draft.language}
                </strong>
              </div>
              <div>
                <span>Details to capture</span>
                <strong>
                  {draft.fields.length}
                  {required ? ` (${required} required)` : ""}
                </strong>
              </div>
              <div>
                <span>Tools</span>
                <strong>{draft.tool_ids.length} selected</strong>
              </div>
              <div>
                <span>Last test call</span>
                <strong>
                  {lastTest
                    ? dateLabel(
                        lastTest.started_at,
                        state?.workspace.timezone || "UTC",
                      )
                    : "Not run"}
                </strong>
              </div>
            </div>
          </section>
          <div className="note spaced">
            <strong>Test before callers do</strong>
            <p>
              Save your changes, then call the agent from your browser in Test
              studio. Every call keeps a copy of the settings it used.
            </p>
          </div>
        </div>
      </div>
      {deleting && (
        <Dialog
          title={`Delete ${agent.name}?`}
          onClose={() => setDeleting(false)}
        >
          <p>
            The agent and its list of fields are removed. Calls it already took,
            and what they captured, are kept.
          </p>
          <div className="actions dialog-actions">
            <button onClick={() => setDeleting(false)}>Cancel</button>
            <button className="primary" disabled={busy} onClick={remove}>
              Delete agent
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
