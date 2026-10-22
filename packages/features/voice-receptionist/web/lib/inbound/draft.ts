import type { Agent, AgentInput, FieldInput } from "./api";

export const VOICES = [
  "Puck",
  "Charon",
  "Kore",
  "Fenrir",
  "Aoede",
  "Leda",
  "Orus",
  "Zephyr",
];
export const LANGUAGES = [
  ["en-US", "English (US)"],
  ["en-GB", "English (UK)"],
  ["es-US", "Spanish (US)"],
  ["fr-FR", "French"],
  ["de-DE", "German"],
  ["hi-IN", "Hindi"],
] as const;
export const DATA_TYPES = [
  "text",
  "phone",
  "email",
  "date",
  "number",
  "boolean",
  "enum",
] as const;
export type DataType = (typeof DATA_TYPES)[number];
export const MAX_FIELDS = 20;
const KEY_RE = /^[a-z][a-z0-9_]{0,62}$/;

export type DraftField = {
  uid: string; // local only, keeps React rows stable while editing
  key: string;
  keyTouched: boolean; // once the user edits the key, stop deriving it from the label
  label: string;
  description: string;
  data_type: DataType;
  enum_text: string; // comma separated while editing
  required: boolean;
};

export type Draft = {
  name: string;
  description: string;
  prompt: string;
  greeting: string;
  voice: string;
  language: string;
  is_active: boolean;
  save_transcript: boolean;
  save_raw_events: boolean;
  save_recording: boolean;
  fields: DraftField[];
  tool_ids: string[];
};

let counter = 0;
export const newField = (): DraftField => ({
  uid: `f${++counter}`,
  key: "",
  keyTouched: false,
  label: "",
  description: "",
  data_type: "text",
  enum_text: "",
  required: false,
});

export function keyFromLabel(label: string): string {
  return label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[^a-z]+/, "")
    .slice(0, 63);
}

export function toDraft(agent?: Agent): Draft {
  return {
    name: agent?.name ?? "",
    description: agent?.description ?? "",
    prompt: agent?.prompt ?? "",
    greeting: agent?.greeting ?? "",
    voice: agent?.voice ?? "Puck",
    language: agent?.language ?? "en-US",
    is_active: agent?.is_active ?? true,
    save_transcript: agent?.save_transcript ?? true,
    save_raw_events: agent?.save_raw_events ?? true,
    save_recording: agent?.save_recording ?? false,
    tool_ids: [...(agent?.tool_ids ?? [])].sort(),
    fields: (agent?.fields ?? []).map((f) => ({
      uid: f.id,
      key: f.key,
      keyTouched: true,
      label: f.label,
      description: f.description ?? "",
      data_type: f.data_type as DataType,
      enum_text: (f.enum_values ?? []).join(", "),
      required: f.required ?? false,
    })),
  };
}

const enumValues = (f: DraftField) =>
  f.enum_text
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

export function toInput(d: Draft): AgentInput {
  return {
    name: d.name.trim(),
    description: d.description.trim() || null,
    prompt: d.prompt.trim(),
    greeting: d.greeting.trim() || null,
    voice: d.voice,
    language: d.language,
    is_active: d.is_active,
    save_transcript: d.save_transcript,
    save_raw_events: d.save_raw_events,
    save_recording: d.save_recording,
    tool_ids: d.tool_ids,
    fields: d.fields.map((f): FieldInput => ({
      key: f.key,
      label: f.label.trim(),
      description: f.description.trim() || null,
      data_type: f.data_type,
      enum_values: f.data_type === "enum" ? enumValues(f) : null,
      required: f.required,
    })),
  };
}

/** The same rules the API enforces, so most mistakes are caught before a round trip. */
export function validate(d: Draft): string | null {
  if (!d.name.trim()) return "Give the agent a name.";
  if (!d.prompt.trim())
    return "Add a prompt: tell the agent who it is and how to help callers.";
  const seen = new Set<string>();
  for (const f of d.fields) {
    const name = f.label.trim() || f.key || "A field";
    if (!f.label.trim()) return "Every field needs a label.";
    if (!KEY_RE.test(f.key))
      return `${name}: the key must be lowercase letters, digits and underscores, starting with a letter.`;
    if (seen.has(f.key))
      return `Two fields use the key "${f.key}". Keys must be unique.`;
    seen.add(f.key);
    if (f.data_type === "enum") {
      const values = enumValues(f);
      if (
        values.length < 1 ||
        values.length > 30 ||
        new Set(values).size !== values.length
      )
        return `${name}: list 1 to 30 different options, separated by commas.`;
    }
  }
  return null;
}
