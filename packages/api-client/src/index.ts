/**
 * Typed client for the FastAPI backend. `schema.d.ts` is generated from the API's
 * OpenAPI spec (`pnpm api-client:generate`), so a backend change that breaks the
 * frontend shows up as a type error, not a runtime surprise.
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];

export function createApiClient(opts: { baseUrl: string; tenantId?: string; role?: string }) {
  const headers: Record<string, string> = {};
  // Dev auth only; replace with a bearer token once real auth lands (see clinic_core/api.py).
  if (opts.tenantId) headers["X-Tenant-Id"] = opts.tenantId;
  if (opts.role) headers["X-Staff-Role"] = opts.role;
  return createClient<paths>({ baseUrl: opts.baseUrl, headers });
}

export type ApiClient = ReturnType<typeof createApiClient>;
