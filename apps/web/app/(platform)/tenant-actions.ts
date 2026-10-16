"use server";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { TENANT_COOKIE } from "@/lib/api";
import { requireAuth } from "@/lib/auth/server";
export async function setTenant(form: FormData) {
  const auth = await requireAuth();
  const tenant = String(form.get("tenant") ?? "").trim();
  if (!auth.memberships.some((m) => m.workspace_id === tenant))
    throw new Error("Clinic access denied");
  (await cookies()).set(TENANT_COOKIE, tenant, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.COOKIE_SECURE === "true",
  });
  redirect("/");
}
