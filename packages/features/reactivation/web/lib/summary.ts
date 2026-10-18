/** Typed, null-safe reads of a run's stored summary and quality report (both are loose JSON). */
type Json = Record<string, unknown> | null | undefined;

export function num(source: Json, key: string): number | null {
  const value = source?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function flag(source: Json, key: string): boolean | null {
  const value = source?.[key];
  return typeof value === "boolean" ? value : null;
}

export function obj(source: Json, key: string): Record<string, unknown> | null {
  const value = source?.[key];
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function strings(source: Json, key: string): string[] {
  const value = source?.[key];
  return Array.isArray(value)
    ? value.filter((v): v is string => typeof v === "string")
    : [];
}

/** The `count` of a quality entry such as {count, patients, sample_ids}. */
export function entryCount(quality: Json, key: string): number {
  return num(obj(quality, key), "count") ?? 0;
}
