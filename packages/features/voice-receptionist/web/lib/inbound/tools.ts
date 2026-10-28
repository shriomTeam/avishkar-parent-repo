import type { Tool, ToolInput } from "./api";

/** The settings of an existing tool as an update request. The auth header value is never sent unless changed. */
export function toToolInput(
  tool: Tool,
  patch: Partial<ToolInput> = {},
): ToolInput {
  return {
    name: tool.name,
    description: tool.description,
    endpoint: tool.endpoint ?? null,
    method: (tool.method === "GET" ? "GET" : "POST") as "GET" | "POST",
    timeout_seconds: tool.timeout_seconds,
    input_schema: tool.input_schema as Record<string, unknown>,
    payload_template:
      (tool.payload_template as Record<string, unknown>) ?? null,
    auth_header_name: tool.auth_header_name ?? null,
    clear_auth: false,
    enabled: tool.enabled,
    ...patch,
  };
}

type Node = {
  type?: string;
  enum?: unknown[];
  minimum?: number;
  properties?: Record<string, Node>;
};

function sample(node: Node): unknown {
  if (node.enum?.length) return node.enum[0];
  switch (node.type) {
    case "number":
    case "integer":
      return node.minimum ?? 1;
    case "boolean":
      return true;
    case "array":
      return [];
    case "object":
      return Object.fromEntries(
        Object.entries(node.properties ?? {}).map(([k, v]) => [k, sample(v)]),
      );
    default:
      return "example";
  }
}

/** A starting point for the "Test tool" box, built from the tool's own schema. */
export function sampleInput(schema: unknown): Record<string, unknown> {
  const value = sample(schema as Node);
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

export const EMPTY_SCHEMA = '{\n  "type": "object",\n  "properties": {}\n}';

/** The captured details a tool's template and endpoint ask for, for example `{{field.phone}}` gives "phone". */
export function fieldKeys(
  template: unknown,
  endpoint: string | null,
): string[] {
  const text = `${JSON.stringify(template ?? {})} ${endpoint ?? ""}`;
  const keys = [
    ...text.matchAll(/\{\{\s*field\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g),
  ];
  return [...new Set(keys.map((m) => m[1] as string))];
}
