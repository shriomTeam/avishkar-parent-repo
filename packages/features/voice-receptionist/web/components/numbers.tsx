"use client";
import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";
import type { PhoneNumber } from "../lib/types";
import { useDemo } from "../lib/demo/provider";
import { Heading, Badge, Dialog, Field, Select, FormError } from "./ui";
export function Numbers() {
  const { state, run, busy } = useDemo();
  const [editing, setEditing] = useState<PhoneNumber | "new" | null>(null);
  const [error, setError] = useState("");
  if (!state) return null;
  const published = state.agents.filter((a) => a.versions.length);
  return (
    <>
      <Heading
        title="Phone numbers"
        description="Connect an inbound number and route it to a published agent."
        actions={
          <button
            className="primary"
            onClick={() => {
              setError("");
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Connect number
          </button>
        }
      />
      <section className="panel">
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                <th>Phone number</th>
                <th>Provider</th>
                <th>Assigned agent</th>
                <th>Status</th>
                <th>Routing</th>
              </tr>
            </thead>
            <tbody>
              {state.numbers.map((n) => (
                <tr key={n.id}>
                  <td>
                    <strong>{n.number}</strong>
                    <small>Sample number</small>
                  </td>
                  <td>{n.provider}</td>
                  <td>
                    {state.agents.find((a) => a.id === n.agentId)?.draft.name ||
                      "Not assigned"}
                  </td>
                  <td>
                    <Badge>{n.agentId ? "Connected" : "Unassigned"}</Badge>
                  </td>
                  <td>
                    <button
                      aria-label={`Manage ${n.number}`}
                      onClick={() => {
                        setError("");
                        setEditing(n);
                      }}
                    >
                      Manage
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <div className="two spaced">
        <section className="panel">
          <h2>How inbound routing works</h2>
          <p>Caller → phone provider → published voice agent</p>
          <div className="rowline">
            <span>Default greeting</span>
            <strong>Agent greeting</strong>
          </div>
          <div className="rowline">
            <span>Outside opening hours</span>
            <strong>Collect callback details</strong>
          </div>
        </section>
        <section className="panel">
          <h2>Before going live</h2>
          <p>
            Verify inbound routing with your provider, test a real call and
            confirm the greeting and consent message.
          </p>
          <Link className="button spaced" href="/voice-receptionist/test">
            Open test studio
          </Link>
        </section>
      </div>
      {editing && (
        <Dialog
          title={
            editing === "new" ? "Connect a phone number" : "Number routing"
          }
          onClose={() => setEditing(null)}
        >
          <p>
            This updates sample routing only. No carrier connection is made.
          </p>
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              const data = new FormData(event.currentTarget);
              const number = String(data.get("number")).trim();
              if (!/^\+[1-9]\d{6,14}$/.test(number)) {
                setError("Enter a valid E.164 number, such as +14155550100.");
                return;
              }
              if (
                state.numbers.some(
                  (n) =>
                    n.number === number &&
                    (editing === "new" || n.id !== editing.id),
                )
              ) {
                setError("This number is already in your workspace.");
                return;
              }
              const item: PhoneNumber = {
                id: editing === "new" ? crypto.randomUUID() : editing.id,
                number,
                provider: String(data.get("provider")),
                agentId: String(data.get("agent")) || null,
              };
              if (
                await run(
                  { type: "save-number", number: item },
                  "Demo routing saved",
                )
              )
                setEditing(null);
            }}
          >
            <Field
              label="Phone number (E.164)"
              name="number"
              type="tel"
              required
              pattern="\+[1-9][0-9]{6,14}"
              placeholder="+14155550100"
              defaultValue={editing === "new" ? "" : editing.number}
            />
            <Select
              label="Provider"
              name="provider"
              defaultValue={editing === "new" ? "Twilio" : editing.provider}
            >
              <option>Twilio</option>
              <option>Telnyx · SIP</option>
            </Select>
            <Select
              label="Assigned agent"
              name="agent"
              defaultValue={editing === "new" ? "" : editing.agentId || ""}
            >
              <option value="">Unassigned</option>
              {published.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.draft.name}
                </option>
              ))}
            </Select>
            {!published.length && (
              <p>Publish an agent before assigning a number.</p>
            )}
            <FormError message={error} />
            <div className="actions dialog-actions">
              <button type="button" onClick={() => setEditing(null)}>
                Cancel
              </button>
              <button className="primary" disabled={busy}>
                Save routing
              </button>
            </div>
          </form>
        </Dialog>
      )}
    </>
  );
}
