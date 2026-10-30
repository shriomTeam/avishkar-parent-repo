"use client";
import Link from "next/link";
import { VoicePreview } from "./voice-preview";
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
import {
  Button,
  buttonStyles,
  H3,
  Muted,
  Note,
  TwoColumns,
  CheckboxField,
} from "@clinic/ui";
import { useVoice } from "../lib/voice/provider";
import { Dropdown, Field, Switch, Textarea } from "./ui";

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
  const { variables, builtinVariables, api } = useVoice();
  const names = [...builtinVariables, ...variables].map((v) => `{{${v.name}}}`);
  return (
    <>
      <TwoColumns>
        <Field
          label="Agent name"
          value={draft.name}
          maxLength={200}
          onChange={(e) => set("name", e.target.value)}
        />
        <Dropdown
          label="Language"
          value={draft.language}
          onChange={(language) => set("language", language)}
          options={LANGUAGES.map(([code, name]) => ({
            value: code,
            label: name,
          }))}
        />
      </TwoColumns>
      <small className="mb-[18px] block text-[12px] text-muted">
        Calls use the selected language. Your prompt and first message stay
        unchanged; captured details use English and transcripts keep the spoken
        language.
      </small>
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
      <small className="block text-[12px] text-muted">
        Tell the agent who it is, what the clinic offers and how to help
        callers. It speaks briefly and does not give medical advice.
      </small>
      <small
        className="mb-[18px] mt-1 block text-[12px] text-muted"
        data-testid="variable-hint"
      >
        Variables you can use here and in the first message: {names.join(", ")}.{" "}
        <Link
          className="text-[#38691d] underline"
          href="/voice-receptionist/variables"
        >
          Manage variables
        </Link>
      </small>
      <Textarea
        label="First message"
        compact
        value={draft.greeting}
        maxLength={1000}
        onChange={(e) => set("greeting", e.target.value)}
      />
      <VoicePreview
        voice={draft.voice}
        language={draft.language}
        greeting={draft.greeting}
        agentName={draft.name}
        api={api}
      >
        <Dropdown
          flush
          label="Voice"
          value={draft.voice}
          onChange={(voice) => set("voice", voice)}
          options={VOICES.map((voice) => ({ value: voice, label: voice }))}
        />
      </VoicePreview>
      <Dropdown
        label="Speech detection"
        value={draft.speech_start_sensitivity}
        onChange={(value) =>
          set("speech_start_sensitivity", value as "high" | "low")
        }
        options={[
          {
            value: "high",
            label: "Sensitive (default)",
            hint: "Better for short or quiet replies",
          },
          {
            value: "low",
            label: "Less sensitive to noise",
            hint: "May miss quiet speech or delay interruptions",
          },
        ]}
      />
      <small className="mb-[18px] block text-[12px] text-muted">
        Applies to new browser and phone calls after saving. Keep the default
        unless you have tested short replies and interruptions on a real phone
        with background noise.
      </small>
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
      <H3>What to capture from callers</H3>
      <Muted>
        The agent listens for these details, reads important ones back to the
        caller, and saves them with the call.
      </Muted>
      {draft.fields.length === 0 && (
        <Note>
          No details yet. Add a field such as the caller’s name or phone number.
        </Note>
      )}
      {draft.fields.map((f) => (
        <div
          className="my-3.5 rounded-[10px] border border-line bg-[#fcfcfd] px-[18px] pb-3.5 pt-4 [&>[data-field]]:mb-3.5 [&_[role=combobox]]:h-[42px] [&_input:not([type=checkbox])]:h-[42px]"
          key={f.uid}
          data-testid="capture-field"
        >
          <div className="mb-3.5 grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)_42px] items-end gap-3 max-app:grid-cols-2">
            <Field
              flush
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
              flush
              label="Key"
              value={f.key}
              maxLength={63}
              onChange={(e) =>
                setField(f.uid, { key: e.target.value, keyTouched: true })
              }
            />
            <Dropdown
              flush
              label="Type"
              value={f.data_type}
              onChange={(type) =>
                setField(f.uid, { data_type: type as DraftField["data_type"] })
              }
              options={DATA_TYPES.map((type) => ({
                value: type,
                label: TYPE_LABELS[type] ?? type,
              }))}
            />
            <Button
              type="button"
              variant="outline"
              size="square"
              className="max-app:justify-self-end"
              aria-label={`Remove field ${f.label || f.key}`}
              onClick={() =>
                set(
                  "fields",
                  draft.fields.filter((x) => x.uid !== f.uid),
                )
              }
            >
              <Trash2 size={16} />
            </Button>
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
          <CheckboxField
            checked={f.required}
            onChange={(required) => setField(f.uid, { required })}
            label="Required: the agent keeps asking until it has this"
          />
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        disabled={draft.fields.length >= MAX_FIELDS}
        onClick={() => set("fields", [...draft.fields, newField()])}
      >
        <Plus size={16} />
        Add field
      </Button>
    </>
  );
}

export function PrivacyFields(props: Props) {
  const { draft } = props;
  const set = setter(props);
  return (
    <>
      <H3>What to save from each call</H3>
      <Muted>
        Captured details are always saved. Transcripts and raw model messages
        can contain patient information, so turn them off if you do not need
        them. Call audio is only kept if you turn on recording below.
      </Muted>
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
      <Switch
        label="Record the call"
        description="Keep the audio of each call (caller and agent) so staff can play it back in Call history. Recordings contain patient information. Tell callers they are being recorded; many places require it."
        checked={draft.save_recording}
        onChange={(v) => set("save_recording", v)}
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
      <H3>Tools this agent can use</H3>
      <Muted>
        During a call the agent can use these to act for the caller. Each run is
        saved with the call.
      </Muted>
      {tools.map((tool) => (
        <Switch
          key={tool.id}
          label={tool.name}
          description={`${tool.description}${tool.enabled ? "" : " (Switched off on the Tools page)"}`}
          checked={draft.tool_ids.includes(tool.id)}
          onChange={(on) => toggle(tool.id, on)}
        />
      ))}
      <Link
        className={buttonStyles("outline", { className: "mt-5" })}
        href="/voice-receptionist/tools"
      >
        Manage tools
      </Link>
    </>
  );
}
