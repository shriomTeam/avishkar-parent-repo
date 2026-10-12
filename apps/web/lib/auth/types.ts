import type { Schemas } from "@clinic/api-client";
export type AuthUser = Schemas["UserOut"];
export type AuthWorkspace = Schemas["WorkspaceOut"];
export type AuthState = Schemas["AuthMeOut"];
export function initials(name: string) {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}
