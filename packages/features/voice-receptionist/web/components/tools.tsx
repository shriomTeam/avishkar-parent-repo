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
import {
  EMPTY_SCHEMA,
  fieldKeys,
  sampleInput,
  toToolInput,
} from "../lib/inbound/tools";
import { dateLabel } from "../lib/format";
import {
  Avatar,
  Button,
  buttonStyles,
  CheckboxField,
  CodeBlock,
  DialogActions,
  FooterRow,
  footerRowStyles,
  H2,
  Muted,
  Note,
  Panel,
  SummaryList,
  TwoColumns,
  WideSplit,
} from "@clinic/ui";
import {
  Heading,
  Badge,
  Dialog,
  Dropdown,
  Field,
  Textarea,
  Switch,
  FormError,
  Empty,
} from "./ui";
import { VoiceBoundary } from "./voice-boundary";
import { LinesSkeleton, ToolsSkeleton } from "./skeletons";

const AUTOFILLED = new Set(["create_lead", "update_lead"]);

export function Tools() {
  return (
    <VoiceBoundary fallback={<ToolsSkeleton />}>
      <ToolList />
    </VoiceBoundary>
  );
}

function ToolList() {
  const { tools, agents, api, upsertTool, removeTool } = useVoice();
  const detailKeys = [
    ...new Set(agents.flatMap((a) => (a.fields ?? []).map((f) => f.key))),
  ];
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
          <Button variant="brand" onClick={() => setAdding(true)}>
            <Plus size={16} />
            Add tool
          </Button>
        }
      />
      <FormError message={error} />
      {tools.length === 0 && (
        <Panel>
          <Empty
            title="No tools yet"
            description="Add an internal tool, such as Create lead, or connect your own API."
          />
        </Panel>
      )}
      <div className="grid gap-5">
        {tools.map((tool) => {
          const custom = tool.kind === "http";
          const uses = agents.filter((a) =>
            a.tool_ids?.includes(tool.id),
          ).length;
          return (
            <Panel key={tool.id} data-testid="tool-card">
              <div className="mb-5 flex items-center justify-between gap-3 max-app:flex-wrap">
                <div className="flex items-center gap-2.5 max-app:flex-wrap">
                  <Avatar>
                    <Code size={20} />
                  </Avatar>
                  <div>
                    <H2 className="shrink-0">{tool.name}</H2>
                    <Muted>{tool.description}</Muted>
                  </div>
                </div>
                <Badge>{tool.enabled ? "Enabled" : "Disabled"}</Badge>
              </div>
              <SummaryList
                items={[
                  ["Type", custom ? "Custom API" : "Built in"],
                  ...(!custom && AUTOFILLED.has(tool.name)
                    ? ([
                        ["Details", "Taken from the agent's captured fields"],
                      ] as [string, string][])
                    : []),
                  ...(!custom
                    ? ([
                        [
                          "Description",
                          tool.description_customized
                            ? "Custom wording"
                            : "Default wording",
                        ],
                      ] as [string, string][])
                    : []),
                  [
                    custom ? "Endpoint" : "Runs",
                    custom
                      ? `${tool.method} ${tool.endpoint}`
                      : "Inside the platform",
                  ],
                  ...(custom
                    ? ([
                        ...(tool.payload_template
                          ? ([["Sends", "A payload template"]] as [
                              string,
                              string,
                            ][])
                          : []),
                        ["Timeout", `${tool.timeout_seconds} seconds`],
                        ["Retries", "GET once · POST never"],
                        [
                          "Auth header",
                          tool.has_auth
                            ? `${tool.auth_header_name} (saved)`
                            : "None",
                        ],
                      ] as [string, string][])
                    : []),
                ]}
              />
              <Switch
                label="Enable tool"
                description="When off, agents cannot use this tool, even mid-call."
                checked={tool.enabled}
                onChange={(enabled) => void toggle(tool, enabled)}
              />
              <FooterRow>
                <span>
                  Used by {uses} {uses === 1 ? "agent" : "agents"}
                </span>
                <div className="flex items-center gap-2.5">
                  {!custom && (
                    <Button
                      variant="outline"
                      onClick={() => setRewording(tool)}
                    >
                      Edit description
                    </Button>
                  )}
                  {custom && (
                    <Button variant="outline" onClick={() => setViewing(tool)}>
                      View input schema
                    </Button>
                  )}
                  <Button variant="outline" onClick={() => setDeleting(tool)}>
                    {custom ? "Delete" : "Remove"}
                  </Button>
                  {custom && (
                    <>
                      <Button
                        variant="outline"
                        onClick={() => setEditing(tool)}
                      >
                        Configure
                      </Button>
                      <Button
                        variant="outline"
                        disabled={!tool.enabled}
                        onClick={() => setTesting(tool)}
                      >
                        Test tool
                      </Button>
                    </>
                  )}
                </div>
              </FooterRow>
            </Panel>
          );
        })}
      </div>
      <WideSplit className="mt-5">
        <Panel>
          <H2>Execution history</H2>
          {executions === null ? (
            <LinesSkeleton />
          ) : executions.length ? (
            executions.map((e) => (
              <Link
                key={e.id}
                className={footerRowStyles}
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
        </Panel>
        <Panel>
          <H2>How tools stay safe</H2>
          <ul className="mb-0 mt-2 grid list-disc gap-2 pl-[18px] text-[14px] text-muted">
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
        </Panel>
      </WideSplit>
      {editing && (
        <ToolDialog
          tool={editing}
          detailKeys={detailKeys}
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
          detailKeys={detailKeys}
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
          run={(input, details) => api.testTool(testing.id, input, details)}
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
          <Muted>
            The arguments the agent supplies when it uses this tool. Anything
            else it sends is dropped before the tool runs.
          </Muted>
          <CodeBlock className="max-h-[55vh] overflow-auto" tabIndex={0}>
            {JSON.stringify(viewing.input_schema, null, 2)}
          </CodeBlock>
          <DialogActions>
            <Button variant="brand" onClick={() => setViewing(null)}>
              Done
            </Button>
          </DialogActions>
        </Dialog>
      )}
      {deleting && (
        <Dialog
          title={`${deleting.kind === "http" ? "Delete" : "Remove"} ${deleting.name}?`}
          onClose={() => setDeleting(null)}
        >
          <Muted>
            Agents stop using this tool. Past runs keep its name in call
            history.
            {deleting.kind === "http" ? "" : " You can add it again later."}
          </Muted>
          <DialogActions>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button
              variant="brand"
              disabled={busy}
              onClick={() => void remove(deleting)}
            >
              {deleting.kind === "http" ? "Delete tool" : "Remove tool"}
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
  );
}

function ToolDialog({
  tool,
  detailKeys,
  onClose,
  onSave,
}: {
  tool: Tool;
  detailKeys: string[];
  onClose: () => void;
  onSave: (body: ToolInput) => Promise<void>;
}) {
  return (
    <Dialog title="Configure API tool" onClose={onClose}>
      <ExternalForm
        tool={tool}
        detailKeys={detailKeys}
        onClose={onClose}
        onSave={onSave}
      />
    </Dialog>
  );
}

function AddToolDialog({
  api,
  detailKeys,
  onClose,
  onAdded,
}: {
  api: InboundApi;
  detailKeys: string[];
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
          detailKeys={detailKeys}
          onClose={onClose}
          onSave={async (body) =>
            onAdded(await api.createTool(body), "Tool saved")
          }
        />
      ) : (
        <>
          {catalog === null ? (
            <LinesSkeleton />
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
              {picked && !picked.added && <Muted>{picked.description}</Muted>}
              {catalog.every((i) => i.added) && (
                <Muted>Every internal tool is already added.</Muted>
              )}
            </>
          )}
          <FormError message={error} />
          <DialogActions>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button
              variant="brand"
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
            </Button>
          </DialogActions>
        </>
      )}
    </Dialog>
  );
}

function ExternalForm({
  tool,
  detailKeys,
  onClose,
  onSave,
}: {
  tool: Tool | null;
  detailKeys: string[];
  onClose: () => void;
  onSave: (body: ToolInput) => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [method, setMethod] = useState(tool?.method === "GET" ? "GET" : "POST");
  const [template, setTemplate] = useState(
    tool?.payload_template
      ? JSON.stringify(tool.payload_template, null, 2)
      : "",
  );
  const [endpoint, setEndpoint] = useState(tool?.endpoint ?? "");
  const sendsDetails = fieldKeys(template, endpoint).length > 0;
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
          let payload: Record<string, unknown> | null = null;
          if (template.trim()) {
            try {
              payload = JSON.parse(template);
              if (
                !payload ||
                Array.isArray(payload) ||
                typeof payload !== "object"
              )
                throw new Error();
            } catch {
              return setError("Enter the payload template as a JSON object.");
            }
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
            payload_template: payload,
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
          compact
          required
          defaultValue={tool?.description ?? ""}
        />
        <Field
          label="Endpoint"
          name="endpoint"
          required
          placeholder="https://api.example.com/leads"
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
        />
        <small className="block text-[12px] text-muted">
          Public HTTPS addresses only. Private and internal addresses are
          blocked. Placeholders work in the path and query, never in the host
          name.
        </small>
        <TwoColumns>
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
        </TwoColumns>
        <TwoColumns>
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
        </TwoColumns>
        {tool?.has_auth && (
          <CheckboxField
            name="clear_auth"
            label="Remove the saved auth header"
          />
        )}
        <Textarea
          label="Input schema"
          name="schema"
          code
          required
          defaultValue={
            tool ? JSON.stringify(tool.input_schema, null, 2) : EMPTY_SCHEMA
          }
        />
        <Textarea
          label="Payload template (optional, JSON)"
          code
          value={template}
          placeholder={
            '{\n  "phone": "{{field.phone}}",\n  "reason": "{{arg.reason}}"\n}'
          }
          onChange={(e) => setTemplate(e.target.value)}
        />
        <small className="block text-[12px] text-muted">
          Leave empty to send the agent&apos;s arguments as they are.{" "}
          <code>{"{{field.name}}"}</code> is a detail captured and checked
          during the call, so the agent never types it.{" "}
          <code>{"{{arg.name}}"}</code> is something the agent supplies, and
          only these appear in its argument list (they must be in the input
          schema). <code>{"{{call.id}}"}</code> and{" "}
          <code>{"{{call.caller_number}}"}</code> describe the call. If a detail
          has not been captured yet, the tool does not run and the agent asks
          the caller first.
          {detailKeys.length > 0 && (
            <>
              {" "}
              Details your agents capture:{" "}
              {detailKeys.map((k) => `{{field.${k}}}`).join(", ")}.
            </>
          )}
        </small>
        {sendsDetails && (
          <Note>
            Details from the call will be sent to this endpoint. Only use
            systems that are allowed to hold patient information (for example
            under a signed BAA).
          </Note>
        )}
        <FormError message={error} />
        <DialogActions>
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="brand" disabled={busy}>
            Save tool
          </Button>
        </DialogActions>
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
  run: (
    input: Record<string, unknown>,
    details: Record<string, string>,
  ) => Promise<ToolTestResult>;
}) {
  const [text, setText] = useState(() =>
    JSON.stringify(sampleInput(tool.input_schema), null, 2),
  );
  const keys = fieldKeys(tool.payload_template, tool.endpoint);
  const [details, setDetails] = useState(() =>
    JSON.stringify(
      Object.fromEntries(keys.map((k) => [k, "example"])),
      null,
      2,
    ),
  );
  const [result, setResult] = useState<ToolTestResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Dialog title={`Test ${tool.name}`} onClose={onClose}>
      <Note>
        This sends a real request to {tool.endpoint}. Use sample data, not
        patient details.
      </Note>
      <Textarea
        label="Sample input (JSON)"
        code
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {keys.length > 0 && (
        <Textarea
          label="Sample captured details (JSON)"
          code
          value={details}
          onChange={(e) => setDetails(e.target.value)}
        />
      )}
      <FormError message={error} />
      {result && (
        <>
          <Badge>{result.ok ? "Success" : "Failed"}</Badge>
          <Muted>
            {result.status ? `Status ${result.status} · ` : ""}
            {result.duration_ms} ms
            {result.error ? ` · ${result.error}` : ""}
          </Muted>
          {result.response !== undefined && result.response !== null && (
            <CodeBlock>{JSON.stringify(result.response, null, 2)}</CodeBlock>
          )}
        </>
      )}
      <DialogActions>
        <Button variant="outline" onClick={onClose}>
          Close
        </Button>
        <Button
          variant="brand"
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
            let sample: Record<string, string> = {};
            try {
              sample = keys.length ? JSON.parse(details) : {};
              if (
                !sample ||
                Array.isArray(sample) ||
                typeof sample !== "object"
              )
                throw new Error();
            } catch {
              return setError("Enter the sample details as a JSON object.");
            }
            setBusy(true);
            setError("");
            setResult(null);
            try {
              setResult(await run(input, sample));
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
        </Button>
      </DialogActions>
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
      <Muted>
        This is what tells the agent when and how to use the tool, so change it
        to match how your clinic works. The name and the arguments stay fixed,
        because they match what the platform saves.
      </Muted>
      <Textarea
        label="Description"
        value={text}
        maxLength={1000}
        onChange={(e) => setText(e.target.value)}
      />
      <FormError message={error} />
      <DialogActions>
        <Button
          type="button"
          variant="outline"
          disabled={text === fallback}
          onClick={() => setText(fallback)}
        >
          Reset to default
        </Button>
        <Button type="button" variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="brand"
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
        </Button>
      </DialogActions>
    </Dialog>
  );
}
