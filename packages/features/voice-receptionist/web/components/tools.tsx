"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Plus, Code } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import {
  ApiError,
  type CatalogItem,
  type InboundApi,
  type Tool,
  type ToolExecution,
  type ToolInput,
  type ToolTestResult,
} from "../lib/inbound/api";
import { EMPTY_SCHEMA, sampleInput, toToolInput } from "../lib/inbound/tools";
import { dateLabel } from "../lib/format";
import {
  Heading,
  Badge,
  Dialog,
  Field,
  Textarea,
  Switch,
  FormError,
  Empty,
} from "./ui";
import { Dropdown } from "./dropdown";
import { VoiceBoundary } from "./voice-boundary";

export function Tools() {
  return (
    <VoiceBoundary>
      <ToolList />
    </VoiceBoundary>
  );
}

function ToolList() {
  const { tools, agents, api, upsertTool, removeTool } = useVoice();
  const { state, notify } = useDemo();
  const [editing, setEditing] = useState<Tool | null>(null);
  const [adding, setAdding] = useState(false);
  const [testing, setTesting] = useState<Tool | null>(null);
  const [deleting, setDeleting] = useState<Tool | null>(null);
  const [viewing, setViewing] = useState<Tool | null>(null);
  const [rewording, setRewording] = useState<Tool | null>(null);
  const [executions, setExecutions] = useState<ToolExecution[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const timezone = state?.workspace.timezone || "UTC";

  useEffect(() => {
    let live = true;
    api
      .listExecutions(10)
      .then((rows) => live && setExecutions(rows))
      .catch(() => live && setExecutions([]));
    return () => {
      live = false;
    };
  }, [api]);

  async function toggle(tool: Tool, enabled: boolean) {
    setError("");
    upsertTool({ ...tool, enabled }); // show the new state at once; undo it if the server refuses
    try {
      upsertTool(await api.updateTool(tool.id, toToolInput(tool, { enabled })));
      notify(enabled ? "Tool enabled" : "Tool disabled");
    } catch (e) {
      upsertTool(tool);
      setError(
        e instanceof ApiError ? e.message : "Could not update the tool.",
      );
    }
  }

  async function remove(tool: Tool) {
    setBusy(true);
    try {
      await api.deleteTool(tool.id);
      removeTool(tool.id);
      notify("Tool deleted");
      setDeleting(null);
    } catch (e) {
      setDeleting(null);
      setError(
        e instanceof ApiError ? e.message : "Could not delete the tool.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Heading
        title="Tools"
        description="Give agents safe, structured actions to perform during a call."
        actions={
          <button className="primary" onClick={() => setAdding(true)}>
            <Plus size={16} />
            Add tool
          </button>
        }
      />
      <FormError message={error} />
      {tools.length === 0 && (
        <section className="panel">
          <Empty
            title="No tools yet"
            description="Add an internal tool, such as Create lead, or connect your own API."
          />
        </section>
      )}
      <div className="tool-list">
        {tools.map((tool) => {
          const custom = tool.kind === "http";
          const uses = agents.filter((a) =>
            a.tool_ids?.includes(tool.id),
          ).length;
          return (
            <section className="panel" key={tool.id}>
              <div className="panelHead">
                <div className="inline">
                  <div className="avatar">
                    <Code size={20} />
                  </div>
                  <div>
                    <h2>{tool.name}</h2>
                    <p>{tool.description}</p>
                  </div>
                </div>
                <Badge>{tool.enabled ? "Enabled" : "Disabled"}</Badge>
              </div>
              <div className="summarylist">
                <div>
                  <span>Type</span>
                  <strong>{custom ? "Custom API" : "Built in"}</strong>
                </div>
                {!custom && (
                  <div>
                    <span>Description</span>
                    <strong>
                      {tool.description_customized
                        ? "Custom wording"
                        : "Default wording"}
                    </strong>
                  </div>
                )}
                <div>
                  <span>{custom ? "Endpoint" : "Runs"}</span>
                  <strong className="wrap-text">
                    {custom
                      ? `${tool.method} ${tool.endpoint}`
                      : "Inside the platform"}
                  </strong>
                </div>
                {custom && (
                  <>
                    <div>
                      <span>Timeout</span>
                      <strong>{tool.timeout_seconds} seconds</strong>
                    </div>
                    <div>
                      <span>Retries</span>
                      <strong>GET once · POST never</strong>
                    </div>
                    <div>
                      <span>Auth header</span>
                      <strong>
                        {tool.has_auth
                          ? `${tool.auth_header_name} (saved)`
                          : "None"}
                      </strong>
                    </div>
                  </>
                )}
              </div>
              <Switch
                label="Enable tool"
                description="When off, agents cannot use this tool, even mid-call."
                checked={tool.enabled}
                onChange={(enabled) => void toggle(tool, enabled)}
              />
              <div className="rowline">
                <span>
                  Used by {uses} {uses === 1 ? "agent" : "agents"}
                </span>
                <div className="actions">
                  {!custom && (
                    <button onClick={() => setRewording(tool)}>
                      Edit description
                    </button>
                  )}
                  {custom && (
                    <button onClick={() => setViewing(tool)}>
                      View input schema
                    </button>
                  )}
                  <button onClick={() => setDeleting(tool)}>
                    {custom ? "Delete" : "Remove"}
                  </button>
                  {custom && (
                    <>
                      <button onClick={() => setEditing(tool)}>
                        Configure
                      </button>
                      <button
                        disabled={!tool.enabled}
                        onClick={() => setTesting(tool)}
                      >
                        Test tool
                      </button>
                    </>
                  )}
                </div>
              </div>
            </section>
          );
        })}
      </div>
      <div className="two spaced">
        <section className="panel">
          <h2>Execution history</h2>
          {executions === null ? (
            <p role="status">Loading…</p>
          ) : executions.length ? (
            executions.map((e) => (
              <Link
                key={e.id}
                className="rowline"
                href={`/voice-receptionist/calls/${e.call_id}`}
              >
                <span>
                  {e.tool_name} · {dateLabel(e.created_at, timezone)} ·{" "}
                  {e.duration_ms} ms
                </span>
                <Badge>{e.success ? "Success" : "Failed"}</Badge>
              </Link>
            ))
          ) : (
            <Empty
              title="No tool runs yet"
              description="When an agent uses a tool during a call, it is listed here."
            />
          )}
        </section>
        <section className="panel">
          <h2>How tools stay safe</h2>
          <ul className="plain-list">
            <li>
              Calls only go to public HTTPS addresses. Internal and private
              addresses are blocked.
            </li>
            <li>Auth header values are encrypted and never shown again.</li>
            <li>
              Tools are limited to 10 seconds, because the caller is waiting.
            </li>
            <li>
              Every run is saved with the call, with its input and result.
            </li>
          </ul>
        </section>
      </div>
      {editing && (
        <ToolDialog
          tool={editing}
          onClose={() => setEditing(null)}
          onSave={async (body) => {
            upsertTool(await api.updateTool(editing.id, body));
            notify("Tool saved");
            setEditing(null);
          }}
        />
      )}
      {adding && (
        <AddToolDialog
          api={api}
          onClose={() => setAdding(false)}
          onAdded={(tool, message) => {
            upsertTool(tool);
            notify(message);
            setAdding(false);
          }}
        />
      )}
      {testing && (
        <TestDialog
          tool={testing}
          onClose={() => setTesting(null)}
          run={(input) => api.testTool(testing.id, input)}
        />
      )}
      {rewording && (
        <WordingDialog
          tool={rewording}
          onClose={() => setRewording(null)}
          onSave={async (description) => {
            upsertTool(
              await api.updateTool(
                rewording.id,
                toToolInput(rewording, { description }),
              ),
            );
            notify("Description saved");
            setRewording(null);
          }}
        />
      )}
      {viewing && (
        <Dialog
          title={`Input schema: ${viewing.name}`}
          onClose={() => setViewing(null)}
        >
          <p className="muted">
            The arguments the agent supplies when it uses this tool. Anything
            else it sends is dropped before the tool runs.
          </p>
          <pre className="code schema-view" tabIndex={0}>
            {JSON.stringify(viewing.input_schema, null, 2)}
          </pre>
          <div className="actions dialog-actions">
            <button className="primary" onClick={() => setViewing(null)}>
              Done
            </button>
          </div>
        </Dialog>
      )}
      {deleting && (
        <Dialog
          title={`${deleting.kind === "http" ? "Delete" : "Remove"} ${deleting.name}?`}
          onClose={() => setDeleting(null)}
        >
          <p>
            Agents stop using this tool. Past runs keep its name in call
            history.
            {deleting.kind === "http" ? "" : " You can add it again later."}
          </p>
          <div className="actions dialog-actions">
            <button onClick={() => setDeleting(null)}>Cancel</button>
            <button
              className="primary"
              disabled={busy}
              onClick={() => void remove(deleting)}
            >
              {deleting.kind === "http" ? "Delete tool" : "Remove tool"}
            </button>
          </div>
        </Dialog>
      )}
    </>
  );
}

function ToolDialog({
  tool,
  onClose,
  onSave,
}: {
  tool: Tool;
  onClose: () => void;
  onSave: (body: ToolInput) => Promise<void>;
}) {
  return (
    <Dialog title="Configure API tool" onClose={onClose}>
      <ExternalForm tool={tool} onClose={onClose} onSave={onSave} />
    </Dialog>
  );
}

function AddToolDialog({
  api,
  onClose,
  onAdded,
}: {
  api: InboundApi;
  onClose: () => void;
  onAdded: (tool: Tool, message: string) => void;
}) {
  const [kind, setKind] = useState<"internal" | "external">("internal");
  const [catalog, setCatalog] = useState<CatalogItem[] | null>(null);
  const [choice, setChoice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .toolCatalog()
      .then((items) => {
        if (!live) return;
        setCatalog(items);
        setChoice(items.find((i) => !i.added)?.key ?? "");
      })
      .catch(() => live && setCatalog([]));
    return () => {
      live = false;
    };
  }, [api]);

  const picked = catalog?.find((i) => i.key === choice);
  return (
    <Dialog title="Add tool" onClose={onClose}>
      <Dropdown
        label="Tool type"
        value={kind}
        options={[
          { value: "internal", label: "Internal: runs inside the platform" },
          { value: "external", label: "External: calls your own API" },
        ]}
        onChange={(value) => {
          setKind(value as "internal" | "external");
          setError("");
        }}
      />
      {kind === "external" ? (
        <ExternalForm
          tool={null}
          onClose={onClose}
          onSave={async (body) =>
            onAdded(await api.createTool(body), "Tool saved")
          }
        />
      ) : (
        <>
          {catalog === null ? (
            <p role="status">Loading…</p>
          ) : (
            <>
              <Dropdown
                label="Action"
                value={choice}
                options={catalog.map((item) => ({
                  value: item.key,
                  label: item.title,
                  hint: item.added ? "already added" : undefined,
                  disabled: item.added,
                }))}
                onChange={setChoice}
              />
              {picked && !picked.added && (
                <p className="muted">{picked.description}</p>
              )}
              {catalog.every((i) => i.added) && (
                <p className="muted">Every internal tool is already added.</p>
              )}
            </>
          )}
          <FormError message={error} />
          <div className="actions dialog-actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button
              className="primary"
              disabled={busy || !picked || picked.added}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  onAdded(await api.addInternalTool(choice), "Tool added");
                } catch (e) {
                  setError(
                    e instanceof ApiError
                      ? e.message
                      : "Could not add the tool.",
                  );
                  setBusy(false);
                }
              }}
            >
              Add tool
            </button>
          </div>
        </>
      )}
    </Dialog>
  );
}

function ExternalForm({
  tool,
  onClose,
  onSave,
}: {
  tool: Tool | null;
  onClose: () => void;
  onSave: (body: ToolInput) => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [method, setMethod] = useState(tool?.method === "GET" ? "GET" : "POST");
  return (
    <>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          const data = new FormData(event.currentTarget);
          const name = String(data.get("name")).trim();
          if (!/^[a-z][a-z0-9_]*$/.test(name))
            return setError("Use a lowercase tool name with underscores.");
          let schema: Record<string, unknown>;
          try {
            schema = JSON.parse(String(data.get("schema")));
            if (!schema || Array.isArray(schema) || typeof schema !== "object")
              throw new Error();
          } catch {
            return setError("Enter valid JSON for the input schema.");
          }
          const headerName = String(data.get("auth_name")).trim();
          const headerValue = String(data.get("auth_value"));
          const body: ToolInput = {
            name,
            description: String(data.get("description")).trim(),
            endpoint: String(data.get("endpoint")).trim(),
            method: data.get("method") === "GET" ? "GET" : "POST",
            timeout_seconds: Number(data.get("timeout")),
            input_schema: schema,
            auth_header_name: headerName || null,
            auth_header_value: headerValue || null,
            clear_auth: data.get("clear_auth") === "on",
            enabled: tool?.enabled ?? true,
          };
          setBusy(true);
          setError("");
          try {
            await onSave(body);
          } catch (e) {
            setError(
              e instanceof ApiError ? e.message : "Could not save the tool.",
            );
            setBusy(false);
          }
        }}
      >
        <Field
          label="Tool name"
          name="name"
          required
          pattern="[a-z][a-z0-9_]*"
          defaultValue={tool?.name ?? ""}
        />
        <Textarea
          label="Description (tells the agent when to use it)"
          name="description"
          className="short-textarea"
          required
          defaultValue={tool?.description ?? ""}
        />
        <Field
          label="Endpoint"
          name="endpoint"
          required
          placeholder="https://api.example.com/leads"
          defaultValue={tool?.endpoint ?? ""}
        />
        <small>
          Public HTTPS addresses only. Private and internal addresses are
          blocked.
        </small>
        <div className="formtwo">
          <Dropdown
            label="HTTP method"
            name="method"
            value={method}
            options={[
              { value: "POST", label: "POST" },
              { value: "GET", label: "GET" },
            ]}
            onChange={setMethod}
          />
          <Field
            label="Timeout (seconds)"
            name="timeout"
            type="number"
            min={1}
            max={10}
            required
            defaultValue={tool?.timeout_seconds ?? 5}
          />
        </div>
        <div className="formtwo">
          <Field
            label="Auth header name (optional)"
            name="auth_name"
            placeholder="Authorization"
            defaultValue={tool?.auth_header_name ?? ""}
          />
          <Field
            label="Auth header value"
            name="auth_value"
            type="password"
            autoComplete="off"
            placeholder={
              tool?.has_auth ? "Saved. Leave blank to keep it." : "Bearer …"
            }
          />
        </div>
        {tool?.has_auth && (
          <label className="inline-check">
            <input type="checkbox" name="clear_auth" />
            Remove the saved auth header
          </label>
        )}
        <Textarea
          label="Input schema"
          name="schema"
          className="code"
          required
          defaultValue={
            tool ? JSON.stringify(tool.input_schema, null, 2) : EMPTY_SCHEMA
          }
        />
        <FormError message={error} />
        <div className="actions dialog-actions">
          <button type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={busy}>
            Save tool
          </button>
        </div>
      </form>
    </>
  );
}

function TestDialog({
  tool,
  onClose,
  run,
}: {
  tool: Tool;
  onClose: () => void;
  run: (input: Record<string, unknown>) => Promise<ToolTestResult>;
}) {
  const [text, setText] = useState(() =>
    JSON.stringify(sampleInput(tool.input_schema), null, 2),
  );
  const [result, setResult] = useState<ToolTestResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={`Test ${tool.name}`} onClose={onClose}>
      <div className="note">
        This sends a real request to {tool.endpoint}. Use sample data, not
        patient details.
      </div>
      <Textarea
        label="Sample input (JSON)"
        className="code"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <FormError message={error} />
      {result && (
        <>
          <Badge>{result.ok ? "Success" : "Failed"}</Badge>
          <p>
            {result.status ? `Status ${result.status} · ` : ""}
            {result.duration_ms} ms
            {result.error ? ` · ${result.error}` : ""}
          </p>
          {result.response !== undefined && result.response !== null && (
            <pre className="code">
              {JSON.stringify(result.response, null, 2)}
            </pre>
          )}
        </>
      )}
      <div className="actions dialog-actions">
        <button onClick={onClose}>Close</button>
        <button
          className="primary"
          disabled={busy}
          onClick={async () => {
            let input: Record<string, unknown>;
            try {
              input = JSON.parse(text);
              if (!input || Array.isArray(input) || typeof input !== "object")
                throw new Error();
            } catch {
              return setError("Enter the sample input as a JSON object.");
            }
            setBusy(true);
            setError("");
            setResult(null);
            try {
              setResult(await run(input));
            } catch (e) {
              setError(
                e instanceof ApiError ? e.message : "The test could not run.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? "Running…" : "Run test"}
        </button>
      </div>
    </Dialog>
  );
}

function WordingDialog({
  tool,
  onClose,
  onSave,
}: {
  tool: Tool;
  onClose: () => void;
  onSave: (description: string) => Promise<void>;
}) {
  const fallback = tool.default_description ?? tool.description;
  const [text, setText] = useState(tool.description);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={`Edit description: ${tool.name}`} onClose={onClose}>
      <p className="muted">
        This is what tells the agent when and how to use the tool, so change it
        to match how your clinic works. The name and the arguments stay fixed,
        because they match what the platform saves.
      </p>
      <Textarea
        label="Description"
        value={text}
        maxLength={1000}
        onChange={(e) => setText(e.target.value)}
      />
      <FormError message={error} />
      <div className="actions dialog-actions">
        <button
          type="button"
          disabled={text === fallback}
          onClick={() => setText(fallback)}
        >
          Reset to default
        </button>
        <button type="button" onClick={onClose}>
          Cancel
        </button>
        <button
          className="primary"
          disabled={busy}
          onClick={async () => {
            if (!text.trim())
              return setError("Describe when the agent should use this tool.");
            setBusy(true);
            setError("");
            try {
              await onSave(text.trim());
            } catch (e) {
              setError(
                e instanceof ApiError
                  ? e.message
                  : "Could not save the description.",
              );
              setBusy(false);
            }
          }}
        >
          Save description
        </button>
      </div>
    </Dialog>
  );
}
