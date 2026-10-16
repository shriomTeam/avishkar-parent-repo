"use client";
import Link from "next/link";
import { useState } from "react";
import { Plus, Code } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import type { Tool } from "../lib/types";
import {
  Heading,
  Badge,
  Dialog,
  Field,
  Select,
  Textarea,
  Switch,
  FormError,
  Empty,
} from "./ui";
export function Tools() {
  const { state, run, busy } = useDemo();
  const [editing, setEditing] = useState<Tool | "new" | null>(null);
  const [error, setError] = useState("");
  const [result, setResult] = useState<Tool | null>(null);
  if (!state) return null;
  const executions = state.calls.flatMap((c) =>
    c.toolExecutions.map((e) => ({ ...e, callId: c.id })),
  );
  return (
    <>
      <Heading
        title="Tools"
        description="Give agents safe, structured actions to perform."
        actions={
          <button
            className="primary"
            onClick={() => {
              setError("");
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Add API tool
          </button>
        }
      />
      <div className="tool-list">
        {state.tools.map((tool) => (
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
            <div className="formtwo">
              <div className="summarylist">
                <div>
                  <span>Method</span>
                  <strong>{tool.method}</strong>
                </div>
                <div>
                  <span>Endpoint</span>
                  <strong className="wrap-text">{tool.endpoint}</strong>
                </div>
                <div>
                  <span>Timeout</span>
                  <strong>{tool.timeoutSeconds} seconds</strong>
                </div>
                <div>
                  <span>Retries</span>
                  <strong>Idempotent only</strong>
                </div>
              </div>
              <div>
                <h3>Input schema</h3>
                <pre className="code">{tool.schema}</pre>
              </div>
            </div>
            <Switch
              label="Enable tool"
              description="Make this action available to agents in this demo."
              checked={tool.enabled}
              onChange={(enabled) => {
                void run(
                  { type: "save-tool", tool: { ...tool, enabled } },
                  "Tool availability updated",
                );
              }}
            />
            <div className="rowline">
              <span>
                Used by{" "}
                {
                  state.agents.filter((a) => a.draft.toolIds.includes(tool.id))
                    .length
                }{" "}
                agents
              </span>
              <div className="actions">
                <button
                  onClick={() => {
                    setError("");
                    setEditing(tool);
                  }}
                >
                  Configure
                </button>
                <button
                  disabled={!tool.enabled}
                  onClick={() => setResult(tool)}
                >
                  Test tool
                </button>
              </div>
            </div>
          </section>
        ))}
      </div>
      <div className="two spaced">
        <section className="panel">
          <h2>Execution history</h2>
          {executions.length ? (
            executions.map((e) => (
              <Link
                key={e.idempotencyKey}
                className="rowline"
                href={`/voice-receptionist/calls/${e.callId}`}
              >
                <span>
                  {e.callId} · {e.toolName}
                </span>
                <Badge>{e.success ? "Success" : "Failed"}</Badge>
              </Link>
            ))
          ) : (
            <Empty title="No sample executions yet" />
          )}
        </section>
        <section className="panel">
          <h2>One action, a clear result</h2>
          <p>
            Tools return a structured result to the agent. Failed requests
            should be logged and the caller offered a callback.
          </p>
          <div className="note spaced">
            Configured endpoints are never contacted in this preview. Test
            results are simulated.
          </div>
        </section>
      </div>
      {result && (
        <Dialog
          title={`Simulated result: ${result.name}`}
          onClose={() => setResult(null)}
        >
          <Badge>Success</Badge>
          <p>
            No request was sent to {result.endpoint}. This result demonstrates
            the tool response interface only.
          </p>
          <pre className="code">
            {JSON.stringify(
              {
                simulated: true,
                tool: result.name,
                success: true,
                duration_ms: 312,
              },
              null,
              2,
            )}
          </pre>
          <button className="primary" onClick={() => setResult(null)}>
            Done
          </button>
        </Dialog>
      )}
      {editing && (
        <Dialog
          title={editing === "new" ? "Add API tool" : "Configure API tool"}
          onClose={() => setEditing(null)}
        >
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const name = String(data.get("name")).trim();
              const endpoint = String(data.get("endpoint")).trim();
              const schema = String(data.get("schema"));
              const description = String(data.get("description")).trim();
              if (!/^[a-z][a-z0-9_]*$/.test(name)) {
                setError("Use a lowercase tool name with underscores.");
                return;
              }
              if (
                state.tools.some(
                  (t) =>
                    t.name === name &&
                    (editing === "new" || t.id !== editing.id),
                )
              ) {
                setError("A tool with this name already exists.");
                return;
              }
              if (
                !endpoint.startsWith("/") &&
                !/^https:\/\/[^\s]+$/.test(endpoint)
              ) {
                setError("Use a relative endpoint or an HTTPS URL.");
                return;
              }
              try {
                const parsed = JSON.parse(schema);
                if (
                  !parsed ||
                  Array.isArray(parsed) ||
                  parsed.type !== "object" ||
                  !parsed.properties ||
                  typeof parsed.properties !== "object" ||
                  Array.isArray(parsed.properties)
                )
                  throw new Error();
                if (
                  parsed.required &&
                  (!Array.isArray(parsed.required) ||
                    parsed.required.some(
                      (key: unknown) =>
                        typeof key !== "string" || !(key in parsed.properties),
                    ))
                )
                  throw new Error();
              } catch {
                setError(
                  'Enter valid JSON with type "object", properties, and valid required field names.',
                );
                return;
              }
              const tool: Tool = {
                id: editing === "new" ? crypto.randomUUID() : editing.id,
                name,
                description,
                endpoint,
                method: data.get("method") as Tool["method"],
                schema,
                enabled: editing === "new" ? true : editing.enabled,
                timeoutSeconds: Number(data.get("timeout")),
              };
              if (
                await run(
                  { type: "save-tool", tool },
                  "Tool definition saved in demo",
                )
              )
                setEditing(null);
            }}
          >
            <Field
              label="Tool name"
              name="name"
              required
              pattern="[a-z][a-z0-9_]*"
              defaultValue={editing === "new" ? "" : editing.name}
            />
            <Field
              label="Description"
              name="description"
              required
              pattern=".*\S.*"
              defaultValue={editing === "new" ? "" : editing.description}
            />
            <Field
              label="Endpoint"
              name="endpoint"
              required
              placeholder="https://api.example.com/leads"
              defaultValue={editing === "new" ? "" : editing.endpoint}
            />
            <div className="formtwo">
              <Select
                label="HTTP method"
                name="method"
                defaultValue={editing === "new" ? "POST" : editing.method}
              >
                <option>POST</option>
                <option>GET</option>
              </Select>
              <Field
                label="Timeout (seconds)"
                name="timeout"
                type="number"
                min={1}
                max={30}
                required
                defaultValue={editing === "new" ? 5 : editing.timeoutSeconds}
              />
            </div>
            <Textarea
              label="Input schema"
              name="schema"
              className="code"
              required
              defaultValue={
                editing === "new"
                  ? '{"type":"object","properties":{}}'
                  : editing.schema
              }
            />
            <FormError message={error} />
            <div className="actions dialog-actions">
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="primary" disabled={busy}>
                Save tool
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
