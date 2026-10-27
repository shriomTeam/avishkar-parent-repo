import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { AuthState } from "./types";

export async function getAuth(): Promise<AuthState | null> {
  const jar = await cookies();
  if (jar.size === 0) return null;
  const response = await fetch(
    `${process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000"}/api/v1/auth/me`,
    {
      headers: { Cookie: jar.toString() },
      cache: "no-store",
      signal: AbortSignal.timeout(8000),
    },
  );
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Authentication service unavailable");
  const auth = (await response.json()) as AuthState;
  return auth;
}
export async function requireAuth(onboarding = false) {
  const auth = await getAuth();
  if (!auth) redirect("/login");
  if (onboarding && !auth.needs_onboarding) redirect("/");
  if (!onboarding && !auth.needs_onboarding && !auth.workspace)
    redirect("/workspaces");
  if (!onboarding && auth.needs_onboarding) redirect("/onboarding");
  return auth;
}
