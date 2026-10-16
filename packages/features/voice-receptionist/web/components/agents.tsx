"use client";
import Link from "next/link";
import { createSeed } from "../lib/demo/seed";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import type { Agent, AgentConfig } from "../lib/types";
import { dateLabel, median } from "../lib/format";
import {
  Heading,
  Badge,
  Dialog,
  Field,
  Select,
  Textarea,
  Tabs,
  Switch,
  FormError,
  Empty,
} from "./ui";
import { VariableTable } from "./variables";
export function AgentList() {
  const { state, run, busy } = useDemo();
  const [creating, setCreating] = useState(false);
  const router = useRouter();
  if (!state) return null;
  return (
    <>
      <Heading
        title="Voice agents"
        description="Configure, test and publish your practice’s voice assistants."
        actions={
          <button className="primary" onClick={() => setCreating(true)}>
            <Plus size={16} />
            Create agent
          </button>
        }
      />
      <div className="agentgrid">
        {state.agents.map((agent) => {
          const calls = state.calls.filter((c) => c.agentId === agent.id);
          return (
            <article className="card agentcard" key={agent.id}>
              <div className="panelHead">
                <div className="avatar">{agent.draft.name[0]}</div>
                <Badge>{agent.versions.length ? "Published" : "Draft"}</Badge>
              </div>
              <h2>{agent.draft.name}</h2>
              <p>{agent.draft.description}</p>
              <div className="inline agent-pills">
                <span className="pill">{agent.draft.language}</span>
                <span className="pill">{agent.draft.voice}</span>
              </div>
              <div className="agentstats">
                <div>
                  <strong>{calls.length}</strong>
                  <small>Total calls</small>
                </div>
                <div>
                  <strong>
                    {calls.length
                      ? `${median(calls.flatMap((c) => (c.latencyMs === null ? [] : [c.latencyMs])))} ms`
                      : "—"}
                  </strong>
                  <small>Median latency</small>
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
      {creating && (
        <Dialog title="Create a voice agent" onClose={() => setCreating(false)}>
          <p>
            Start with a name and a purpose. Configure its voice and prompt
            next.
          </p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const name = String(form.get("name")).trim();
              if (!name) return;
              const agent: Agent = {
                id: crypto.randomUUID(),
                versions: [],
                draft: {
                  ...createSeed().agents[0]!.draft,
                  name,
                  description: String(form.get("purpose")),
                  prompt:
                    "Greet callers, answer practice questions and offer a staff callback.",
                  toolIds: [],
                },
              };
              if (
                await run(
                  { type: "save-agent", agent, event: "Draft agent created" },
                  "Draft agent created",
                )
              ) {
                setCreating(false);
                router.push(`/voice-receptionist/agents/${agent.id}`);
              }
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
              <option>Front desk receptionist</option>
              <option>Enquiry assistant</option>
              <option>After-hours assistant</option>
            </Select>
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
  const { state } = useDemo();
  if (!state) return null;
  const agent = state.agents.find((a) => a.id === id);
  if (!agent)
    return (
      <section className="panel">
        <Empty
          title="Agent not found"
          description="This agent may have been a demo draft cleared by a refresh."
        />
        <Link className="button" href="/voice-receptionist/agents">
          Back to agents
        </Link>
      </section>
    );
  return <Editor key={id} agent={agent} />;
}
function Editor({ agent }: { agent: Agent }) {
  const { state, run, busy } = useDemo();
  const [draft, setDraft] = useState<AgentConfig>({ ...agent.draft });
  const [tab, setTab] = useState("Configuration");
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState("");
  if (!state) return null;
  const update = <K extends keyof AgentConfig>(key: K, value: AgentConfig[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));
  async function save(publish = false) {
    if (!draft.name.trim() || !draft.prompt.trim() || !draft.greeting.trim()) {
      setError("Name, system prompt and first message are required.");
      setTab("Configuration");
      setPublishing(false);
      return;
    }
    setError("");
    const clean = { ...draft, name: draft.name.trim() };
    const versions = publish
      ? [
          ...agent.versions,
          {
            id: crypto.randomUUID(),
            number: (agent.versions.at(-1)?.number || 0) + 1,
            publishedAt: new Date().toISOString(),
            config: structuredClone(clean),
          },
        ]
      : agent.versions;
    if (
      await run(
        {
          type: "save-agent",
          agent: { ...agent, draft: clean, versions },
          event: publish ? "Agent version published" : "Agent draft saved",
        },
        publish
          ? "Agent version published in demo"
          : "Draft saved for this preview session",
      )
    )
      setPublishing(false);
  }
  const dirty = JSON.stringify(draft) !== JSON.stringify(agent.draft);
  const version = agent.versions.at(-1);
  const lastTest = state.calls.find(
    (c) => c.agentId === agent.id && c.phone === "Browser test",
  );
  return (
    <>
      <Heading
        title={draft.name}
        description={`Agent configuration · ${version ? `Live version v${version.number}` : "Unpublished draft"}${dirty ? " · Unsaved changes" : ""}`}
        actions={
          <>
            <Link
              className="button"
              href={`/voice-receptionist/test?agent=${agent.id}`}
            >
              Test agent
            </Link>
            <button disabled={busy} onClick={() => save()}>
              Save draft
            </button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => setPublishing(true)}
            >
              Publish
            </button>
          </>
        }
      />
      <Tabs
        tabs={["Configuration", "Variables", "Tools", "Versions"]}
        value={tab}
        onChange={setTab}
      />
      <FormError message={error} />
      <div className="editor">
        <section className="panel" role="tabpanel" aria-label={tab}>
          {tab === "Configuration" && (
            <>
              <div className="formtwo">
                <Field
                  label="Agent name"
                  value={draft.name}
                  maxLength={80}
                  onChange={(e) => update("name", e.target.value)}
                />
                <Select
                  label="Language"
                  value={draft.language}
                  onChange={(e) => update("language", e.target.value)}
                >
                  {["English (US)", "English (UK)", "Hindi"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </Select>
              </div>
              <Field
                label="Description"
                value={draft.description}
                onChange={(e) => update("description", e.target.value)}
              />
              <Textarea
                label="System prompt"
                value={draft.prompt}
                onChange={(e) => update("prompt", e.target.value)}
              />
              <small>
                Use variables such as {"{{company_name}}"} to personalise each
                call.
              </small>
              <Textarea
                label="First message"
                className="short-textarea"
                value={draft.greeting}
                onChange={(e) => update("greeting", e.target.value)}
              />
              <div className="formtwo">
                <Select
                  label="Voice"
                  value={draft.voice}
                  onChange={(e) => update("voice", e.target.value)}
                >
                  <option>Sophie</option>
                  <option>Alex</option>
                </Select>
                <Select
                  label="Model"
                  value={draft.model}
                  onChange={(e) => update("model", e.target.value)}
                >
                  <option>GPT-4.1 mini</option>
                  <option>GPT-4.1</option>
                </Select>
              </div>
              <Switch
                label="Allow interruptions"
                description="Let callers speak naturally while the agent is talking."
                checked={draft.interruptions}
                onChange={(value) => update("interruptions", value)}
              />
            </>
          )}
          {tab === "Variables" && (
            <>
              <h3>Variables available to this agent</h3>
              <p>
                Static values are set by your workspace. Call values resolve
                when a conversation starts.
              </p>
              <VariableTable variables={state.variables} />
              <Link
                className="button spaced"
                href="/voice-receptionist/variables"
              >
                Manage variables
              </Link>
            </>
          )}
          {tab === "Tools" && (
            <>
              <h3>Available actions</h3>
              {state.tools.map((tool) => (
                <Switch
                  key={tool.id}
                  label={tool.name}
                  description={`${tool.description}${tool.enabled ? "" : " (Disabled in workspace)"}`}
                  checked={draft.toolIds.includes(tool.id)}
                  onChange={(checked) =>
                    update(
                      "toolIds",
                      checked
                        ? [...draft.toolIds, tool.id]
                        : draft.toolIds.filter((id) => id !== tool.id),
                    )
                  }
                />
              ))}
              <div className="note spaced">
                Confirm the caller’s details before saving an enquiry. Changes
                are saved with this agent’s draft.
              </div>
              <Link className="button spaced" href="/voice-receptionist/tools">
                View tool configuration
              </Link>
            </>
          )}
          {tab === "Versions" && (
            <>
              {!agent.versions.length ? (
                <Empty
                  title="No published versions"
                  description="Publish a draft to create an immutable demo snapshot."
                />
              ) : (
                <div className="tablewrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Version</th>
                        <th>Status</th>
                        <th>Published</th>
                        <th>Prompt snapshot</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...agent.versions].reverse().map((v, index) => (
                        <tr key={v.id}>
                          <td>v{v.number}</td>
                          <td>
                            <Badge>
                              {index === 0 ? "Published" : "Archived"}
                            </Badge>
                          </td>
                          <td>
                            {dateLabel(v.publishedAt, state.workspace.timezone)}
                          </td>
                          <td>
                            <details>
                              <summary>View configuration</summary>
                              <pre className="code">
                                {JSON.stringify(v.config, null, 2)}
                              </pre>
                            </details>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p>
                Calls retain the version and agent name used when they started.
              </p>
            </>
          )}
        </section>
        <div>
          <section className="panel">
            <div className="panelHead">
              <h2>Agent readiness</h2>
              <Badge>{version ? "Published" : "Draft"}</Badge>
            </div>
            <div className="summarylist">
              <div>
                <span>Prompt</span>
                <strong>
                  {draft.prompt.trim() ? "Configured" : "Missing"}
                </strong>
              </div>
              <div>
                <span>Voice & model</span>
                <strong>Configured</strong>
              </div>
              <div>
                <span>Tools</span>
                <strong>{draft.toolIds.length} selected</strong>
              </div>
              <div>
                <span>Phone number</span>
                <strong>
                  {state.numbers.some((n) => n.agentId === agent.id)
                    ? "Connected"
                    : "Not assigned"}
                </strong>
              </div>
              <div>
                <span>Last saved test</span>
                <strong>{lastTest ? "Completed" : "Not run"}</strong>
              </div>
            </div>
          </section>
          <div className="note spaced">
            <strong>Test before you publish</strong>
            <p>
              Save your draft, then check the greeting and captured details in
              Test studio. Navigate away only after saving changes you want to
              keep.
            </p>
          </div>
        </div>
      </div>
      {publishing && (
        <Dialog
          title={`Publish ${draft.name}?`}
          onClose={() => setPublishing(false)}
        >
          <p>
            This creates a version snapshot in the prototype. Existing call
            records keep their original version.
          </p>
          <div className="note">
            {lastTest
              ? "A simulated test has been completed. This does not establish production readiness."
              : "Run a simulated test before publishing. Production release checks come later."}
          </div>
          <div className="actions dialog-actions">
            <button onClick={() => setPublishing(false)}>Cancel</button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => save(true)}
            >
              Publish version
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}
