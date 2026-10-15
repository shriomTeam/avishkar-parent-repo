"use client";
import { useState } from "react";
import { Plus } from "lucide-react";
import { useDemo } from "../lib/demo/provider";
import { resolvePrompt } from "../lib/format";
import type { Variable } from "../lib/types";
import { Heading, Dialog, Field, FormError } from "./ui";
export function VariableTable({ variables }: { variables: Variable[] }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr>
            <th>Variable</th>
            <th>Value / source</th>
            <th>Type</th>
          </tr>
        </thead>
        <tbody>
          {variables.map((v) => (
            <tr key={v.id}>
              <td>
                <code>{`{{${v.name}}}`}</code>
              </td>
              <td>{v.value}</td>
              <td>
                <span className="pill">{v.type}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
        title="Variables"
        description="Personalise agent context without rewriting the prompt."
        actions={
          <button
            className="primary"
            onClick={() => {
              setError("");
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Add variable
          </button>
        }
      />
      <section className="panel">
        <VariableTable variables={state.variables} />
        <div className="inline spaced">
          {state.variables
            .filter((v) => v.type === "Static")
            .map((v) => (
              <button
                key={v.id}
                onClick={() => {
                  setError("");
                  setEditing(v);
                }}
              >
                Edit {v.name}
              </button>
            ))}
        </div>
      </section>
      <div className="two spaced">
        <section className="panel">
          <h2>Prompt template</h2>
          <pre className="code">{template}</pre>
        </section>
        <section className="panel">
          <h2>Resolved preview</h2>
          <pre className="code">
            {resolvePrompt(template, state.variables, {
              caller_number: "+1 (415) 555-0101",
            })}
          </pre>
          <p>
            Runtime values are examples. Missing variables stay visible as
            placeholders.
          </p>
        </section>
      </div>
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
            <div className="actions dialog-actions">
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="primary" disabled={busy}>
                Save variable
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
