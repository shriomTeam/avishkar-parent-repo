import "server-only";

import { createApiClient, type Schemas } from "@clinic/api-client";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const TENANT_COOKIE = "clinic_tenant";

/** Server-side API client for the current request's tenant (dev auth: tenant id in a cookie). */
export async function api() {
  const tenantId = (await cookies()).get(TENANT_COOKIE)?.value;
  return { client: createApiClient({ baseUrl: API_URL, tenantId }), tenantId };
}

export type Me = Schemas["MeOut"];

export async function getMe(): Promise<Me | null> {
  const { client, tenantId } = await api();
  if (!tenantId) return null;
  const { data } = await client.GET("/me");
  return data ?? null;
}

/** Feature pages call this first: a tenant without the feature never sees the page. */
export async function requireFeature(key: string): Promise<Me> {
  const me = await getMe();
  if (!me || !me.features.find((f) => f.key === key && f.enabled)) notFound();
  return me;
}
