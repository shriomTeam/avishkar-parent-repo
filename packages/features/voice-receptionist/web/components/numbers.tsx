"use client";
import Link from "next/link";
import { useState } from "react";
import { Plus } from "lucide-react";
import type { PhoneNumber } from "../lib/types";
import { useDemo } from "../lib/demo/provider";
import { useVoiceStatus } from "../lib/voice/provider";
import {
  Button,
  buttonStyles,
  DataTable,
  DialogActions,
  FooterRow,
  H2,
  Muted,
  Panel,
  Td,
  Th,
  Tr,
  WideSplit,
} from "@clinic/ui";
import { Heading, Badge, Dialog, Dropdown, Field, FormError } from "./ui";
export function Numbers() {
  const { state, run, busy } = useDemo();
  const { agents } = useVoiceStatus();
  const [editing, setEditing] = useState<PhoneNumber | "new" | null>(null);
  const [error, setError] = useState("");
  if (!state) return null;
  const published = (agents ?? []).filter((a) => a.is_active);
  return (
    <>
      <Heading
        demo
        title="Phone numbers"
        description="Connect an inbound number and route it to an agent."
        actions={
          <Button
            variant="brand"
            onClick={() => {
              setError("");
              setEditing("new");
            }}
          >
            <Plus size={16} />
            Connect number
          </Button>
        }
      />
      <Panel>
        <DataTable>
          <thead>
            <tr>
              <Th>Phone number</Th>
              <Th>Provider</Th>
              <Th>Assigned agent</Th>
              <Th>Status</Th>
              <Th>Routing</Th>
            </tr>
          </thead>
          <tbody>
            {state.numbers.map((n) => (
              <Tr key={n.id}>
                <Td>
                  <strong>{n.number}</strong>
                  <small className="block text-[12px] text-muted">
                    Sample number
                  </small>
                </Td>
                <Td>{n.provider}</Td>
                <Td>
                  {(agents ?? []).find((a) => a.id === n.agentId)?.name ||
                    "Not assigned"}
                </Td>
                <Td>
                  <Badge>{n.agentId ? "Connected" : "Unassigned"}</Badge>
                </Td>
                <Td>
                  <Button
                    variant="outline"
                    aria-label={`Manage ${n.number}`}
                    onClick={() => {
                      setError("");
                      setEditing(n);
                    }}
                  >
                    Manage
                  </Button>
                </Td>
              </Tr>
            ))}
          </tbody>
        </DataTable>
      </Panel>
      <WideSplit className="mt-5">
        <Panel>
          <H2>How inbound routing works</H2>
          <Muted>Caller → phone provider → published voice agent</Muted>
          <FooterRow>
            <span>Default greeting</span>
            <strong>Agent greeting</strong>
          </FooterRow>
          <FooterRow>
            <span>Outside opening hours</span>
            <strong>Collect callback details</strong>
          </FooterRow>
        </Panel>
        <Panel>
          <H2>Before going live</H2>
          <Muted>
            Verify inbound routing with your provider, test a real call and
            confirm the greeting and consent message.
          </Muted>
          <Link
            className={buttonStyles("outline", { className: "mt-5" })}
            href="/voice-receptionist/test"
          >
            Open test studio
          </Link>
        </Panel>
      </WideSplit>
      {editing && (
        <Dialog
          title={
            editing === "new" ? "Connect a phone number" : "Number routing"
          }
          onClose={() => setEditing(null)}
        >
          <Muted>
            This updates sample routing only. No carrier connection is made.
          </Muted>
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
            <Dropdown
              label="Provider"
              name="provider"
              defaultValue={editing === "new" ? "Twilio" : editing.provider}
              options={[
                { value: "Twilio", label: "Twilio" },
                { value: "Telnyx · SIP", label: "Telnyx · SIP" },
              ]}
            />
            <Dropdown
              label="Assigned agent"
              name="agent"
              defaultValue={editing === "new" ? "" : editing.agentId || ""}
              options={[
                { value: "", label: "Unassigned" },
                ...published.map((a) => ({ value: a.id, label: a.name })),
              ]}
            />
            {!published.length && (
              <Muted>Create an active agent before assigning a number.</Muted>
            )}
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
                Save routing
              </Button>
            </DialogActions>
          </form>
        </Dialog>
      )}
    </>
  );
}
