"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { TENANT_COOKIE } from "@/lib/api";

/** Dev-only stand-in for login: remember which tenant to act as. */
export async function setTenant(form: FormData) {
  const tenant = String(form.get("tenant") ?? "").trim();
  (await cookies()).set(TENANT_COOKIE, tenant, { httpOnly: true, sameSite: "lax", path: "/" });
  redirect("/");
}
