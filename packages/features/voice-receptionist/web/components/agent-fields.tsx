"use client";
import Link from "next/link";
import { Plus, Trash2 } from "lucide-react";
import type { Tool } from "../lib/inbound/api";
import {
  DATA_TYPES,
  LANGUAGES,
  MAX_FIELDS,
  VOICES,
  keyFromLabel,
  newField,
  type Draft,
  type DraftField,
} from "../lib/inbound/draft";
import { Field, Select, Switch, Textarea } from "./ui";

type Props = { draft: Draft; onChange: (draft: Draft) => void };

const TYPE_LABELS: Record<string, string> = {
  text: "Text",
  phone: "Phone number",
  email: "Email",
  date: "Date",
  number: "Number",
  boolean: "Yes / no",
  enum: "One of a list",
};

function setter({ draft, onChange }: Props) {
  return <K extends keyof Draft>(key: K, value: Draft[K]) =>
    onChange({ ...draft, [key]: value });
}

export function ConfigurationFields(props: Props) {
  const { draft } = props;
  const set = setter(props);
  return (
    <>
      <div className="formtwo">
        <Field
          label="Agent name"
          value={draft.name}
          maxLength={200}
          onChange={(e) => set("name", e.target.value)}
        />
        <Select
          label="Language"
          value={draft.language}
          onChange={(e) => set("language", e.target.value)}
        >
          {LANGUAGES.map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </Select>
      </div>
      <Field
        label="Description"
        value={draft.description}
        maxLength={1000}
        onChange={(e) => set("description", e.target.value)}
      />
      <Textarea
        label="System prompt"
        value={draft.prompt}
        maxLength={20000}
        onChange={(e) => set("prompt", e.target.value)}
      />
      <small>
        Tell the agent who it is, what the clinic offers and how to help
        callers. It speaks briefly and does not give medical advice.
      </small>
      <Textarea
        label="First message"
        className="short-textarea"
        value={draft.greeting}
        maxLength={1000}
        onChange={(e) => set("greeting", e.target.value)}
      />
      <div className="formtwo">
        <Select
          label="Voice"
          value={draft.voice}
          onChange={(e) => set("voice", e.target.value)}
        >
          {VOICES.map((voice) => (
            <option key={voice}>{voice}</option>
          ))}
        </Select>
      </div>
      <Switch
        label="Agent is active"
        description="Inactive agents cannot take calls."
        checked={draft.is_active}
        onChange={(v) => set("is_active", v)}
      />
    </>
  );
}

export function CaptureFields(props: Props) {
  const { draft } = props;
  const set = setter(props);
  const setField = (uid: string, patch: Partial<DraftField>) =>
    set(
      "fields",
      draft.fields.map((f) => (f.uid === uid ? { ...f, ...patch } : f)),
    );
  return (
    <>
      <h3>What to capture from callers</h3>
      <p className="muted">
        The agent listens for these details, reads important ones back to the
        caller, and saves them with the call.
      </p>
      {draft.fields.length === 0 && (
        <div className="note">
          No details yet. Add a field such as the caller’s name or phone number.
        </div>
      )}
      {draft.fields.map((f) => (
        <div className="capture-field" key={f.uid} data-testid="capture-field">
          <div className="capture-row">
            <Field
              label="Label"
              value={f.label}
              maxLength={200}
              onChange={(e) =>
                setField(f.uid, {
                  label: e.target.value,
                  ...(f.keyTouched
                    ? {}
                    : { key: keyFromLabel(e.target.value) }),
                })
              }
            />
            <Field
              label="Key"
              value={f.key}
              maxLength={63}
              onChange={(e) =>
                setField(f.uid, { key: e.target.value, keyTouched: true })
              }
            />
            <Select
              label="Type"
              value={f.data_type}
              onChange={(e) =>
                setField(f.uid, {
                  data_type: e.target.value as DraftField["data_type"],
                })
              }
            >
              {DATA_TYPES.map((type) => (
                <option key={type} value={type}>
                  {TYPE_LABELS[type]}
                </option>
              ))}
            </Select>
            <button
              type="button"
              className="icon-button"
              aria-label={`Remove field ${f.label || f.key}`}
              onClick={() =>
                set(
                  "fields",
                  draft.fields.filter((x) => x.uid !== f.uid),
                )
              }
            >
              <Trash2 size={16} />
            </button>
          </div>
          {f.data_type === "enum" && (
            <Field
              label="Options (separated by commas)"
              value={f.enum_text}
              onChange={(e) => setField(f.uid, { enum_text: e.target.value })}
            />
          )}
          <Field
            label="Hint for the agent (optional)"
            value={f.description}
            maxLength={1000}
            onChange={(e) => setField(f.uid, { description: e.target.value })}
          />
          <label className="inline-check">
            <input
              type="checkbox"
              checked={f.required}
              onChange={(e) => setField(f.uid, { required: e.target.checked })}
            />
            Required: the agent keeps asking until it has this
          </label>
        </div>
      ))}
      <button
        type="button"
        disabled={draft.fields.length >= MAX_FIELDS}
        onClick={() => set("fields", [...draft.fields, newField()])}
      >
        <Plus size={16} />
        Add field
      </button>
    </>
  );
}

export function PrivacyFields(props: Props) {
  const { draft } = props;
  const set = setter(props);
  return (
    <>
      <h3>What to save from each call</h3>
      <p className="muted">
        Captured details are always saved. Transcripts and raw model messages
        can contain patient information, so turn them off if you do not need
        them. Audio is never stored.
      </p>
      <Switch
        label="Save the transcript"
        description="Store the words spoken in each call, turn by turn."
        checked={draft.save_transcript}
        onChange={(v) => set("save_transcript", v)}
      />
      <Switch
        label="Save raw model responses"
        description="Keep the unprocessed messages from the AI model (no audio) for each call."
        checked={draft.save_raw_events}
        onChange={(v) => set("save_raw_events", v)}
      />
    </>
  );
}

export function ToolFields({
  draft,
  onChange,
  tools,
}: Props & { tools: Tool[] }) {
  const toggle = (id: string, on: boolean) =>
    onChange({
      ...draft,
      tool_ids: on
        ? [...draft.tool_ids, id]
        : draft.tool_ids.filter((x) => x !== id),
    });
  return (
    <>
      <h3>Tools this agent can use</h3>
      <p className="muted">
        During a call the agent can use these to act for the caller. Each run is
        saved with the call.
      </p>
      {tools.map((tool) => (
        <Switch
          key={tool.id}
          label={tool.name}
          description={`${tool.description}${tool.enabled ? "" : " (Switched off on the Tools page)"}`}
          checked={draft.tool_ids.includes(tool.id)}
          onChange={(on) => toggle(tool.id, on)}
        />
      ))}
      <Link className="button spaced" href="/voice-receptionist/tools">
        Manage tools
      </Link>
    </>
  );
}
