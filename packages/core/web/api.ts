import "server-only";
import { createApiClient, type Schemas } from "@clinic/api-client";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { getAuth } from "./auth/server";

export const API_URL =
  process.env.BACKEND_INTERNAL_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000";
export const TENANT_COOKIE = "clinic_tenant";

export async function api() {
  const auth = await getAuth();
  const tenantId = auth?.workspace?.id;
  const requestHeaders: Record<string, string> = {
    Cookie: (await cookies()).toString(),
    Origin: process.env.PUBLIC_APP_ORIGIN ?? "http://localhost:3000",
  };
  if (auth) requestHeaders["X-CSRF-Token"] = auth.csrf_token;
  return {
    client: createApiClient({
      baseUrl: API_URL,
      tenantId,
      headers: requestHeaders,
    }),
    tenantId,
    requestHeaders,
  };
}
export type Me = Schemas["MeOut"];
export async function getMe(): Promise<Me | null> {
  const { client, tenantId } = await api();
  if (!tenantId) return null;
  const { data, response } = await client.GET("/me");
  if (!response.ok)
    throw new Error(
      "Unable to load clinic access. Please refresh or sign in again.",
    );
  return data ?? null;
}
export async function requireFeature(key: string): Promise<Me> {
  const me = await getMe();
  if (
    !me ||
    !me.features.find((f) => f.key === key && f.enabled && f.accessible)
  )
    notFound();
  return me;
}

export async function requireManagement() {
  const me = await getMe();
  if (!me || !["owner", "office_manager"].includes(me.role)) notFound();
  return me;
}
