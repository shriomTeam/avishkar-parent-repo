"use client";
import { initials } from "@clinic/core/web/auth/types";
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
  Avatar,
  Button,
  buttonStyles,
  DialogActions,
  H2,
  Muted,
  Note,
  Panel,
  PanelHead,
  Pill,
  SidebarLayout,
  SummaryList,
} from "@clinic/ui";
import {
  Heading,
  Badge,
  Dialog,
  Dropdown,
  Field,
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
import { AgentEditorSkeleton, AgentsSkeleton } from "./skeletons";

export function AgentList() {
  return (
    <VoiceBoundary fallback={<AgentsSkeleton />}>
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
          <Button variant="brand" onClick={() => setCreating(true)}>
            <Plus size={16} />
            Create agent
          </Button>
        }
      />
      {agents.length === 0 ? (
        <Panel>
          <Empty
            title="No voice agents yet"
            description="Create your first agent, then try it from your browser in Test studio."
          />
        </Panel>
      ) : (
        <div className="grid grid-cols-3 gap-[22px] max-[1100px]:grid-cols-2 max-app:grid-cols-1 [&>*]:min-w-0">
          {agents.map((agent) => {
            const agentCalls = calls.filter((c) => c.agent_id === agent.id);
            return (
              <article
                className="rounded-[13px] border border-line bg-white p-6 transition-transform hover:-translate-y-[3px] max-app:p-[18px]"
                key={agent.id}
              >
                <div className="mb-5 flex items-center justify-between gap-3 max-app:flex-wrap">
                  <Avatar size="lg">{initials(agent.name)}</Avatar>
                  <Badge>{agent.is_active ? "Active" : "Disabled"}</Badge>
                </div>
                <H2 className="mb-1 mt-3.5">{agent.name}</H2>
                <Muted>{agent.description || "No description yet."}</Muted>
                <div className="mt-[18px] flex flex-wrap items-center gap-2.5">
                  <Pill>{agent.language}</Pill>
                  <Pill>{agent.voice}</Pill>
                </div>
                <div className="my-[22px] flex gap-[25px] border-t border-line pt-[18px]">
                  <div>
                    <strong className="text-[16px]">{agentCalls.length}</strong>
                    <small className="block text-[12px] text-muted">
                      Total calls
                    </small>
                  </div>
                  <div>
                    <strong className="text-[16px]">
                      {agent.fields?.length ?? 0}
                    </strong>
                    <small className="block text-[12px] text-muted">
                      Details captured
                    </small>
                  </div>
                </div>
                <Link
                  href={`/voice-receptionist/agents/${agent.id}`}
                  className={buttonStyles("outline", { className: "w-full" })}
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
          <Muted>
            Start with a name and a purpose. We fill in a prompt and the usual
            details to capture; you can change everything next.
          </Muted>
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
            <Dropdown
              label="Purpose"
              name="purpose"
              options={Object.keys(STARTERS).map((purpose) => ({
                value: purpose,
                label: purpose,
              }))}
            />
            <FormError message={error} />
            <DialogActions>
              <Button
                type="button"
                variant="outline"
                onClick={() => setCreating(false)}
              >
                Cancel
              </Button>
              <Button type="submit" variant="brand" disabled={busy}>
                Create agent
              </Button>
            </DialogActions>
          </form>
        </Dialog>
      )}
    </>
  );
}

export function AgentEditor({ id }: { id: string }) {
  return (
    <VoiceBoundary fallback={<AgentEditorSkeleton />}>
      <EditorLoader id={id} />
    </VoiceBoundary>
  );
}

function EditorLoader({ id }: { id: string }) {
  const { agents } = useVoice();
  const agent = agents.find((a) => a.id === id);
  if (!agent)
    return (
      <Panel>
        <Empty
          title="Agent not found"
          description="This agent may have been deleted."
        />
        <Link
          className={buttonStyles("outline")}
          href="/voice-receptionist/agents"
        >
          Back to agents
        </Link>
      </Panel>
    );
  return <Editor key={agent.id} agent={agent} />;
}

function Editor({ agent }: { agent: Agent }) {
  const { api, calls, tools, upsertAgent, removeAgent, reloadVariables } =
    useVoice();
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
      void reloadVariables(); // which agents use which variable may have changed
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
      void reloadVariables();
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
              className={buttonStyles("outline")}
              href={`/voice-receptionist/test?agent=${agent.id}`}
            >
              Test agent
            </Link>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => setDeleting(true)}
            >
              Delete
            </Button>
            <Button variant="brand" disabled={busy || !dirty} onClick={save}>
              Save changes
            </Button>
          </>
        }
      />
      <Tabs
        tabs={["Configuration", "What to capture", "Tools", "Data & privacy"]}
        value={tab}
        onChange={setTab}
      />
      <FormError message={error} />
      <SidebarLayout>
        <Panel role="tabpanel" aria-label={tab}>
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
        </Panel>
        <div>
          <Panel>
            <PanelHead
              title="Agent readiness"
              action={<Badge>{agent.is_active ? "Active" : "Disabled"}</Badge>}
            />
            <SummaryList
              items={[
                ["Prompt", draft.prompt.trim() ? "Configured" : "Missing"],
                ["Voice", `${draft.voice} · ${draft.language}`],
                [
                  "Details to capture",
                  `${draft.fields.length}${required ? ` (${required} required)` : ""}`,
                ],
                ["Tools", `${draft.tool_ids.length} selected`],
                [
                  "Last test call",
                  lastTest
                    ? dateLabel(
                        lastTest.started_at,
                        state?.workspace.timezone || "UTC",
                      )
                    : "Not run",
                ],
              ]}
            />
          </Panel>
          <Note className="mt-5">
            <strong>Test before callers do</strong>
            <p>
              Save your changes, then call the agent from your browser in Test
              studio. Every call keeps a copy of the settings it used.
            </p>
          </Note>
        </div>
      </SidebarLayout>
      {deleting && (
        <Dialog
          title={`Delete ${agent.name}?`}
          onClose={() => setDeleting(false)}
        >
          <Muted>
            The agent and its list of fields are removed. Calls it already took,
            and what they captured, are kept.
          </Muted>
          <DialogActions>
            <Button variant="outline" onClick={() => setDeleting(false)}>
              Cancel
            </Button>
            <Button variant="brand" disabled={busy} onClick={remove}>
              Delete agent
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
  );
}
