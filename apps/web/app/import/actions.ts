"use server";

import type { Schemas } from "@clinic/api-client";

import { API_URL, api } from "@/lib/api";

// Multipart uploads go through fetch directly; the JSON endpoints use the typed client.
async function postForm<T>(path: string, form: FormData): Promise<{ data?: T; error?: string }> {
  const { tenantId } = await api();
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    body: form,
    headers: tenantId ? { "X-Tenant-Id": tenantId } : {},
  });
  const body = await res.json();
  return res.ok ? { data: body as T } : { error: typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail) };
}

export async function suggestMapping(form: FormData) {
  return postForm<Schemas["SuggestOut"]>("/imports/suggest", form);
}

export async function runImport(form: FormData) {
  return postForm<Schemas["ImportOut"]>("/imports", form);
}
