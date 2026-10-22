"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import { resolvePrompt } from "../lib/format";
import type { Variable } from "../lib/types";
import {
  Button,
  CodeBlock,
  DataTable,
  DialogActions,
  H2,
  Muted,
  Panel,
  Pill,
  Td,
  Th,
  Tr,
  WideSplit,
} from "@clinic/ui";
import { Heading, Dialog, Field, FormError } from "./ui";
export function VariableTable({ variables }: { variables: Variable[] }) {
  return (
    <DataTable>
      <thead>
        <tr>
          <Th>Variable</Th>
          <Th>Value / source</Th>
          <Th>Type</Th>
        </tr>
      </thead>
      <tbody>
        {variables.map((v) => (
          <Tr key={v.id}>
            <Td>
              <code>{`{{${v.name}}}`}</code>
            </Td>
            <Td>{v.value}</Td>
            <Td>
              <Pill>{v.type}</Pill>
            </Td>
          </Tr>
        ))}
      </tbody>
    </DataTable>
  );
}
export function Variables() {
  const { state, run, busy } = useDemo();
  const [editing, setEditing] = useState<Variable | "new" | null>(null);
  const [error, setError] = useState("");
  if (!state) return null;
  const template =
    "You are {{agent_name}}, the AI receptionist for {{company_name}}.\nThe caller’s number is {{caller_number}}.";
  return (
    <>
      <Heading
        demo
        title="Variables"
        description="Personalise agent context without rewriting the prompt."
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
      <Panel>
        <VariableTable variables={state.variables} />
        <div className="mt-5 flex items-center gap-2.5 max-app:flex-wrap">
          {state.variables
            .filter((v) => v.type === "Static")
            .map((v) => (
              <Button
                key={v.id}
                variant="outline"
                onClick={() => {
                  setError("");
                  setEditing(v);
                }}
              >
                Edit {v.name}
              </Button>
            ))}
        </div>
      </Panel>
      <WideSplit className="mt-5">
        <Panel>
          <H2>Prompt template</H2>
          <CodeBlock>{template}</CodeBlock>
        </Panel>
        <Panel>
          <H2>Resolved preview</H2>
          <CodeBlock>
            {resolvePrompt(template, state.variables, {
              caller_number: "+1 (415) 555-0101",
            })}
          </CodeBlock>
          <Muted>
            Runtime values are examples. Missing variables stay visible as
            placeholders.
          </Muted>
        </Panel>
      </WideSplit>
      {editing && (
        <Dialog
          title={
            editing === "new" ? "Add a static variable" : `Edit ${editing.name}`
          }
          onClose={() => setEditing(null)}
        >
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const form = new FormData(event.currentTarget);
              const name = String(form.get("name")).trim();
              const value = String(form.get("value")).trim();
              if (!/^[a-z][a-z0-9_]*$/.test(name) || !value) {
                setError(
                  "Use a lowercase variable name and a non-empty value.",
                );
                return;
              }
              if (
                state.variables.some(
                  (v) =>
                    v.name === name &&
                    (editing === "new" || v.id !== editing.id),
                )
              ) {
                setError("A variable with this name already exists.");
                return;
              }
              if (
                await run(
                  {
                    type: "save-variable",
                    variable: {
                      id: editing === "new" ? crypto.randomUUID() : editing.id,
                      name,
                      value,
                      type: "Static",
                    },
                  },
                  "Static variable saved",
                )
              )
                setEditing(null);
            }}
          >
            <Field
              label="Name"
              name="name"
              required
              pattern="[a-z][a-z0-9_]*"
              defaultValue={editing === "new" ? "" : editing.name}
            />
            <Field
              label="Value"
              name="value"
              required
              pattern=".*\S.*"
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
    </>
  );
}
