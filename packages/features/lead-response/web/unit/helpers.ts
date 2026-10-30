import { readFileSync } from "node:fs";
import type { Config } from "../lib/settings.ts";

type Raw = { base: Config; cases: { id: string; valid: boolean; set: Record<string, unknown> }[] };
const raw = JSON.parse(readFileSync(new URL("./fixtures/rule-cases.json", import.meta.url), "utf8")) as Raw;

/** A value in the cases file may be {"$repeat": [text, times]} so a 321-character message need not be written out. */
function expand(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(expand);
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if ("$repeat" in obj) {
      const [text, times] = obj.$repeat as [string, number];
      return text.repeat(times);
    }
    return Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, expand(v)]));
  }
  return value;
}

/** The standard settings, the same object the server's tests compare to the model's own defaults. */
export const DEFAULTS = raw.base;
export const CASES = raw.cases.map((c) => ({
  id: c.id,
  valid: c.valid,
  config: { ...structuredClone(DEFAULTS), ...(expand(c.set) as object) } as Config,
}));

export function defaults(): Config {
  return structuredClone(DEFAULTS);
}
