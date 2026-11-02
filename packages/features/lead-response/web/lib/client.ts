"use client";
import { createApiClient } from "@clinic/api-client";

/** Typed browser client. Next forwards /api/platform/* to the API; the session cookie goes with it. */
export function browserClient(csrfToken: string, tenantId: string | undefined) {
  return createApiClient({
    baseUrl: "/api/platform",
    tenantId,
    headers: { "X-CSRF-Token": csrfToken },
  });
}
