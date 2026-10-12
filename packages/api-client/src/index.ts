/**
 * Typed client for the FastAPI backend. `schema.d.ts` is generated from the API's
 * OpenAPI spec (`pnpm api-client:generate`), so a backend change that breaks the
 * frontend shows up as a type error, not a runtime surprise.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];

export function createApiClient(opts: { baseUrl: string; tenantId?: string; role?: string; headers?: Record<string, string> }) {
  const headers: Record<string, string> = { ...opts.headers };
  // A tenant ID is a selection hint. The API verifies session membership and derives the role.
  if (opts.tenantId) headers["X-Tenant-Id"] = opts.tenantId;
  if (opts.role) headers["X-Staff-Role"] = opts.role;
  return createClient<paths>({ baseUrl: opts.baseUrl, headers, credentials: "same-origin" });
}

export type ApiClient = ReturnType<typeof createApiClient>;
