"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import {
  Button,
  DataTable,
  DialogActions,
  H2,
  Muted,
  Note,
  Panel,
  Td,
  Th,
  Tr,
} from "@clinic/ui";
import { useDemo } from "../lib/demo/provider";
import { useVoice } from "../lib/voice/provider";
import { ApiError, type Variable } from "../lib/inbound/api";
import { Heading, Dialog, Empty, Field, FormError, Textarea } from "./ui";
import { VoiceBoundary } from "./voice-boundary";

export function Variables() {
  return (
    <VoiceBoundary>
      <VariableList />
    </VoiceBoundary>
  );
}

const NAME_PATTERN = "[a-z][a-z0-9_]*";

function VariableList() {
  const { api, variables, builtinVariables, upsertVariable, removeVariable } =
    useVoice();
  const { notify } = useDemo();
  const [editing, setEditing] = useState<Variable | "new" | null>(null);
  const [deleting, setDeleting] = useState<Variable | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(form: FormData) {
    const name = String(form.get("name") ?? "").trim();
    const value = String(form.get("value") ?? "").trim();
    if (editing === "new" && !new RegExp(`^${NAME_PATTERN}$`).test(name))
      return setError(
        "Use lowercase letters, numbers and underscores, starting with a letter.",
      );
    if (!value) return setError("Enter the text this variable stands for.");
    setBusy(true);
    setError("");
    try {
      const saved =
        editing === "new"
          ? await api.createVariable(name, value)
          : await api.updateVariable((editing as Variable).id, value);
      upsertVariable(saved);
      notify("Variable saved");
      setEditing(null);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Could not save the variable.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove(variable: Variable) {
    setBusy(true);
    try {
      await api.deleteVariable(variable.id);
      removeVariable(variable.id);
      notify("Variable deleted");
      setDeleting(null);
    } catch (e) {
      setDeleting(null);
      setError(
        e instanceof ApiError ? e.message : "Could not delete the variable.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Heading
        title="Variables"
        description="Reusable text for your agents' prompts, such as your opening hours."
        actions={
          <Button
            variant="brand"
            onClick={() => {
              setError("");
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Add variable
          </Button>
        }
      />
      {!editing && <FormError message={error} />}
      <Panel>
        <H2>Your variables</H2>
        {variables.length === 0 ? (
          <Empty
            title="No variables yet"
            description="Add one, such as hours or address, then write it as {{hours}} in an agent's prompt."
          />
        ) : (
          <DataTable>
            <thead>
              <tr>
                <Th>Variable</Th>
                <Th>Value</Th>
                <Th>Used by</Th>
                <Th>Actions</Th>
              </tr>
            </thead>
            <tbody>
              {variables.map((v) => (
                <Tr key={v.id}>
                  <Td>
                    <code>{`{{${v.name}}}`}</code>
                  </Td>
                  <Td className="max-w-[420px] truncate">{v.value}</Td>
                  <Td>
                    {v.used_by?.length ? v.used_by.join(", ") : "No agent"}
                  </Td>
                  <Td>
                    <div className="flex items-center gap-2.5">
                      <Button
                        variant="outline"
                        aria-label={`Edit ${v.name}`}
                        onClick={() => {
                          setError("");
                          setEditing(v);
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="outline"
                        aria-label={`Delete ${v.name}`}
                        onClick={() => {
                          setError("");
                          setDeleting(v);
                        }}
                      >
                        Delete
                      </Button>
                    </div>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Panel>
      <Panel className="mt-5">
        <H2>Built-in variables</H2>
        <Muted>
          Filled in by the platform when each call starts. You do not set these.
        </Muted>
        <DataTable>
          <thead>
            <tr>
              <Th>Variable</Th>
              <Th>What it is</Th>
              <Th>Example</Th>
            </tr>
          </thead>
          <tbody>
            {builtinVariables.map((b) => (
              <Tr key={b.name}>
                <Td>
                  <code>{`{{${b.name}}}`}</code>
                </Td>
                <Td>{b.description}</Td>
                <Td>{b.example}</Td>
              </Tr>
            ))}
          </tbody>
        </DataTable>
      </Panel>
      <Note className="mt-5">
        <strong>How to use them</strong>
        <p>
          Write a variable in double braces, such as {"{{hours}}"}, in an
          agent&apos;s prompt or first message. It is filled in when a call
          starts, so a change applies to the next call. Details the agent
          collects during a call, such as the caller&apos;s name, are saved with
          the call and cannot be used in the prompt.
        </p>
      </Note>
      {editing && (
        <Dialog
          title={editing === "new" ? "Add a variable" : `Edit ${editing.name}`}
          onClose={() => setEditing(null)}
        >
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              await save(new FormData(event.currentTarget));
            }}
          >
            {editing === "new" ? (
              <Field
                label="Name"
                name="name"
                required
                maxLength={64}
                pattern={NAME_PATTERN}
                placeholder="hours"
                hint="Lowercase letters, numbers and underscores. The name cannot be changed later."
              />
            ) : (
              <Muted>
                Name: <code>{`{{${editing.name}}}`}</code>. The name cannot be
                changed, because prompts refer to it.
              </Muted>
            )}
            <Textarea
              label="Value"
              name="value"
              compact
              required
              maxLength={1000}
              defaultValue={editing === "new" ? "" : editing.value}
            />
            <FormError message={error} />
            <DialogActions>
              <Button
                type="button"
                variant="outline"
                onClick={() => setEditing(null)}
              >
                Cancel
              </Button>
              <Button type="submit" variant="brand" disabled={busy}>
                Save variable
              </Button>
            </DialogActions>
          </form>
        </Dialog>
      )}
      {deleting && (
        <Dialog
          title={`Delete ${deleting.name}?`}
          onClose={() => setDeleting(null)}
        >
          <Muted>
            An agent whose prompt still uses{" "}
            <code>{`{{${deleting.name}}}`}</code> blocks the delete. Remove it
            from the prompt first.
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
              Delete variable
            </Button>
          </DialogActions>
        </Dialog>
      )}
    </>
  );
}
