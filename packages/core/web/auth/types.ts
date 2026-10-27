import type { Schemas } from "@clinic/api-client";
export type AuthUser = Schemas["UserOut"];
export type AuthWorkspace = Schemas["WorkspaceOut"];
export type AuthState = Schemas["AuthMeOut"];
export function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const firstAndLast =
    parts.length > 1 ? [parts[0], parts[parts.length - 1]] : parts;
  return firstAndLast
    .map((part) => part?.[0] ?? "")
    .join("")
    .toUpperCase();
}
